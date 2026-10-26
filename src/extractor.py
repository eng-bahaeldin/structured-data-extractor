import json
import os
import time
from typing import Literal, Optional
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import ValidationError

from src.schemas import InvoiceExtraction, ExtractionResult
from src.fallback import (
    format_validation_error_summary,
    build_reflection_prompt,
    write_to_dlq,
    attempt_heuristic_repair,
)


def sanitize_schema_for_gemini(schema: dict) -> dict:
    """Recursively converts OpenAPI incompatible keys (like exclusiveMinimum) to Gemini-compliant keys."""
    if not isinstance(schema, dict):
        return schema
    cleaned = {}
    for k, v in schema.items():
        if k == "exclusiveMinimum":
            cleaned["minimum"] = v
        elif k == "exclusiveMaximum":
            cleaned["maximum"] = v
        elif isinstance(v, dict):
            cleaned[k] = sanitize_schema_for_gemini(v)
        elif isinstance(v, list):
            cleaned[k] = [sanitize_schema_for_gemini(item) if isinstance(item, dict) else item for item in v]
        else:
            cleaned[k] = v
    return cleaned


class SchemaExtractor:
    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: Literal["gemini", "openai"] = "gemini",
    ):
        self.provider = provider
        key = api_key or os.getenv("GEMINI_API_KEY")
        self.gemini_client = genai.Client(api_key=key)
        self.model_name = "gemini-3.8-flash"

        # Sanitize Pydantic schema once at initialization
        raw_schema = InvoiceExtraction.model_json_schema()
        self.clean_schema = sanitize_schema_for_gemini(raw_schema)

    def _call_gemini_structured(self, prompt: str) -> dict:
        """Invokes Gemini using cleaned schema dictionary."""
        response = self.gemini_client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=self.clean_schema,
            ),
        )
        return json.loads(response.text)

    def extract_with_retry(
        self,
        raw_text: str,
        max_retries: int = 3,
        enable_reflection: bool = True,
    ) -> ExtractionResult:
        error_logs: list[str] = []
        last_payload: dict = {}

        # -------------------------------------------------------------
        # STAGE 1: Constrained Decoding
        # -------------------------------------------------------------
        try:
            parsed_json = self._call_gemini_structured(
                f"Extract procurement records matching schema from text:\n{raw_text}"
            )
            last_payload = parsed_json
            extraction = InvoiceExtraction.model_validate(parsed_json)
            return ExtractionResult(
                validated_data=extraction,
                raw_payload=extraction.model_dump(),
                attempts_used=1,
                error_log=[],
                execution_status="SUCCESS",
            )
        except ValidationError as val_err:
            error_logs.append(f"Stage 1 Validation Failure:\n{format_validation_error_summary(val_err)}")
        except Exception as err:
            error_logs.append(f"Stage 1 Ingestion Failure: {str(err)}")

        if not enable_reflection:
            dlq_file = write_to_dlq(raw_text, last_payload, error_logs)
            return ExtractionResult(
                validated_data=None,
                raw_payload=last_payload,
                attempts_used=1,
                error_log=error_logs,
                execution_status="DLQ_FAILED",
            )

        # -------------------------------------------------------------
        # STAGE 2: Reflection Loop with 503 Backoff
        # -------------------------------------------------------------
        context_slice = raw_text[:3500]
        for attempt in range(2, max_retries + 1):
            prompt = build_reflection_prompt(
                context_chunk=context_slice,
                malformed_payload=last_payload,
                error_summary=error_logs[-1],
            )
            try:
                # Add a brief 1-second pause to prevent 503 burst congestion
                time.sleep(1.0)

                resp = self.gemini_client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=self.clean_schema,
                    ),
                )
                last_payload = json.loads(resp.text)
                validated = InvoiceExtraction.model_validate(last_payload)
                error_logs.append(f"Attempt {attempt}: Reflection loop resolved all schema conflicts.")
                return ExtractionResult(
                    validated_data=validated,
                    raw_payload=validated.model_dump(),
                    attempts_used=attempt,
                    error_log=error_logs,
                    execution_status="REPAIRED_VIA_REFLECTION",
                )
            except ValidationError as val_err:
                error_logs.append(f"Attempt {attempt} Validation Failed:\n{format_validation_error_summary(val_err)}")
            except APIError as api_err:
                error_logs.append(f"Attempt {attempt} API Error ({api_err.code}): {api_err.message}")
                time.sleep(2.0)  # Extra backoff on 503
            except Exception as e:
                error_logs.append(f"Attempt {attempt} Exception: {str(e)}")

        # -------------------------------------------------------------
        # STAGE 3: Heuristic Repair & DLQ Fallback
        # -------------------------------------------------------------
        if last_payload:
            try:
                repaired = attempt_heuristic_repair(json.dumps(last_payload))
                validated = InvoiceExtraction.model_validate(repaired)
                error_logs.append("Stage 3: Salvaged record using heuristic repair.")
                return ExtractionResult(
                    validated_data=validated,
                    raw_payload=validated.model_dump(),
                    attempts_used=max_retries,
                    error_log=error_logs,
                    execution_status="REPAIRED_VIA_REFLECTION",
                )
            except Exception:
                error_logs.append("Stage 3 Heuristic repair failed validation criteria.")

        dlq_path = write_to_dlq(raw_text, last_payload, error_logs)
        error_logs.append(f"Max retries exceeded. Record routed to DLQ: {dlq_path}")
        return ExtractionResult(
            validated_data=None,
            raw_payload=last_payload,
            attempts_used=max_retries,
            error_log=error_logs,
            execution_status="DLQ_FAILED",
        )
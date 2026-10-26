import json
import time
from pathlib import Path
from typing import Any, Dict, List
import json_repair
from pydantic import ValidationError


def format_validation_error_summary(exc: ValidationError) -> str:
    """Extracts field paths and human-readable error reasons."""
    summary = []
    for err in exc.errors():
        field_path = " -> ".join(str(loc) for loc in err.get("loc", []))
        message = err.get("msg", "Validation error")
        bad_value = err.get("input", None)
        summary.append(f"• Location: [{field_path}] | Issue: {message} | Provided Value: {repr(bad_value)}")
    return "\n".join(summary)


def build_reflection_prompt(context_chunk: str, malformed_payload: dict, error_summary: str) -> str:
    """Builds a targeted correction prompt without token bloat."""
    return f"""The previous JSON extraction failed schema validation.

VALIDATION ERRORS:
{error_summary}

FAILED JSON PAYLOAD:
{json.dumps(malformed_payload, indent=2, default=str)}

RELEVANT SOURCE EXCERPT:
{context_chunk[:2500]}

INSTRUCTIONS:
1. Fix all validation errors identified above.
2. Standardize dates to YYYY-MM-DD format.
3. Ensure line items sum up to: (total_amount - tax_amount) within 0.02 tolerance.
4. Output strictly valid JSON conforming to the schema."""


def write_to_dlq(raw_input: str, failed_payload: Any, errors: List[str], dlq_folder: str = "dlq") -> str:
    """Writes failed extraction records to a Dead-Letter Queue directory."""
    folder = Path(dlq_folder)
    folder.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    file_path = folder / f"dlq_failure_{timestamp}.json"
    record = {
        "timestamp": timestamp,
        "raw_input_snippet": raw_input[:1000],
        "failed_payload": failed_payload,
        "error_trace": errors,
        "status": "UNRESOLVED_DLQ",
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)
    return str(file_path)


def attempt_heuristic_repair(raw_json: str) -> Dict[str, Any]:
    """Recovers unescaped characters, open brackets, and malformed JSON syntax."""
    repaired = json_repair.repair_json(raw_json, return_objects=True)
    return repaired if isinstance(repaired, dict) else {}
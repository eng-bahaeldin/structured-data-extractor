import sys
from pathlib import Path

# Anchor project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
import os
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from src.extractor import SchemaExtractor
from src.fallback import format_validation_error_summary
from src.schemas import InvoiceExtraction

load_dotenv()

st.set_page_config(page_title="Enterprise Schema Pipeline", layout="wide")
st.title("🛡️ Enterprise Schema Pipeline")

DLQ_DIR = Path("dlq")
RESOLVED_DIR = DLQ_DIR / "resolved"
DLQ_DIR.mkdir(parents=True, exist_ok=True)
RESOLVED_DIR.mkdir(parents=True, exist_ok=True)

tab_extract, tab_dlq = st.tabs(["🚀 Live Extractor", "📥 DLQ Review & Resolution"])

# =====================================================================
# TAB 1: Live Ingestion & Extraction Engine
# =====================================================================
with tab_extract:
    with st.sidebar:
        st.header("Pipeline Configuration")

        provider = st.radio(
            "Select LLM Engine:",
            options=["Google Gemini (Free Tier)", "OpenAI"],
            index=0,
        )
        selected_provider = "gemini" if "Gemini" in provider else "openai"

        default_key = (
            os.getenv("GEMINI_API_KEY", "")
            if selected_provider == "gemini"
            else os.getenv("OPENAI_API_KEY", "")
        )

        api_key = st.text_input(
            f"{'Gemini' if selected_provider == 'gemini' else 'OpenAI'} API Key",
            value=default_key,
            type="password",
            help="Get a free Gemini key from aistudio.google.com" if selected_provider == "gemini" else "",
        )

        enable_reflection = st.toggle("Enable Reflection Loop", value=True)
        max_retries = st.slider("Max Retries", min_value=1, max_value=5, value=3)

        st.divider()
        st.subheader("Simulate Edge Cases")
        if st.button("Load Corrupted OCR Failure"):
            st.session_state["input_text"] = "Corrupted unreadable scan: @@!! 8234792348729384729384729384"
        if st.button("Load Reconciliation Mismatch"):
            st.session_state["input_text"] = """INVOICE #INV-9021
Vendor: Precision Tooling LLC
Date: 2024-10-14
Currency: USD

Line Items:
1. CNC Milling Bit | Qty: 2 | Unit Price: $50.00 | Total: $100.00

Subtotal: $100.00
Tax: $10.00
Total Due: $240.00
"""

    input_data = st.text_area(
        "Raw Unstructured Document (Text, OCR, or HTML)",
        value=st.session_state.get("input_text", ""),
        height=180,
    )

    if st.button("Run Extraction Pipeline", type="primary"):
        if not api_key:
            st.error(f"Please provide your {selected_provider.upper()} API Key in the sidebar.")
        elif not input_data.strip():
            st.warning("Please enter text or click a sample edge case.")
        else:
            extractor = SchemaExtractor(api_key=api_key, provider=selected_provider)
            with st.spinner(f"Extracting with {selected_provider.upper()} and evaluating validation constraints..."):
                result = extractor.extract_with_retry(
                    raw_text=input_data,
                    max_retries=max_retries,
                    enable_reflection=enable_reflection,
                )

            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Ingested Source")
                st.code(input_data, language="text")

            with col2:
                st.subheader("Validated Output")
                if result.execution_status == "SUCCESS":
                    st.success(f"Status: {result.execution_status} (Attempt {result.attempts_used})")
                elif result.execution_status == "REPAIRED_VIA_REFLECTION":
                    st.warning(f"Status: {result.execution_status} (Self-healed on Attempt {result.attempts_used})")
                else:
                    st.error(f"Status: {result.execution_status} (Terminal Fallback)")

                if result.validated_data:
                    st.metric("Total Extracted",
                              f"{result.validated_data.currency} {result.validated_data.total_amount}")
                    st.success("Math Reconciliation: PASS")
                    st.json(result.validated_data.model_dump())
                else:
                    st.error("Math Reconciliation: FAIL / REJECTED")
                    st.json(result.raw_payload or {"status": "DLQ_FILE_RECORDED"})

            st.divider()
            st.subheader("Step-by-Step Telemetry & Reflection Logs")
            if result.error_log:
                for log in result.error_log:
                    st.text(log)
            else:
                st.info("Direct parse passed Stage 1 with zero schema violations.")

# =====================================================================
# TAB 2: Human-in-the-Loop Dead-Letter Queue (DLQ) Review
# =====================================================================
with tab_dlq:
    st.subheader("Human-in-the-Loop Exception Management")
    st.caption(
        "Inspect failed extractions, rectify validation mismatches, and re-validate into downstream ERP contracts.")

    active_dlq_files = sorted(
        [f for f in DLQ_DIR.glob("*.json") if f.is_file()],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )

    col_metric1, col_metric2 = st.columns(2)
    col_metric1.metric("Unresolved Queue Items", len(active_dlq_files))
    resolved_count = len(list(RESOLVED_DIR.glob("*.json")))
    col_metric2.metric("Resolved Records", resolved_count)

    if not active_dlq_files:
        st.info("The Dead-Letter Queue is currently empty. No unresolved exceptions.")
    else:
        selected_file = st.selectbox(
            "Select Failure Incident to Review:",
            options=active_dlq_files,
            format_func=lambda
                p: f"{p.name} — Modified {datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}",
        )

        with open(selected_file, "r", encoding="utf-8") as f:
            try:
                record_data = json.load(f)
            except Exception as e:
                record_data = {"error": f"Failed to parse file: {str(e)}"}

        meta_col, edit_col = st.columns([1, 1])

        with meta_col:
            st.markdown("#### Diagnostic Telemetry")
            st.caption(f"File: `{selected_file.name}`")

            with st.expander("Raw Ingested Snippet", expanded=False):
                st.text(record_data.get("raw_input_snippet", "No raw snippet available"))

            st.markdown("**Error Traces Encountered:**")
            error_traces = record_data.get("error_trace", [])
            if error_traces:
                for trace in error_traces:
                    st.code(trace, language="text")
            else:
                st.write("No error trace logged.")

            if st.button("🗑️ Dismiss Incident (Delete)", type="secondary"):
                selected_file.unlink(missing_ok=True)
                st.toast(f"Deleted {selected_file.name}")
                st.rerun()

        with edit_col:
            st.markdown("#### Payload Correction & Re-Validation")
            failed_payload = record_data.get("failed_payload") or {}
            payload_str = json.dumps(failed_payload, indent=2)

            edited_json_str = st.text_area(
                "Editable JSON Payload",
                value=payload_str,
                height=320,
            )

            if st.button("✅ Validate & Resolve Incident", type="primary"):
                try:
                    parsed_dict = json.loads(edited_json_str)
                    validated_record = InvoiceExtraction.model_validate(parsed_dict)

                    record_data["failed_payload"] = validated_record.model_dump()
                    record_data["status"] = "MANUALLY_RESOLVED"
                    record_data["resolved_at"] = datetime.utcnow().isoformat()

                    resolved_path = RESOLVED_DIR / selected_file.name
                    with open(resolved_path, "w", encoding="utf-8") as f_out:
                        json.dump(record_data, f_out, indent=2, default=str)

                    selected_file.unlink(missing_ok=True)
                    st.success("Reconciliation Passed! Record validated and archived.")
                    st.json(validated_record.model_dump())
                    st.rerun()
                except json.JSONDecodeError as json_err:
                    st.error(f"Malformed JSON syntax: {str(json_err)}")
                except ValidationError as val_err:
                    st.error("Validation Gate Rejected the Edit:")
                    st.code(format_validation_error_summary(val_err), language="text")
# tests/test_fallbacks.py
from unittest.mock import MagicMock
from src.extractor import SchemaExtractor


def test_reflection_loop_recovery(monkeypatch):
    extractor = SchemaExtractor(api_key="mock-key")

    # Force Stage 1 failure
    extractor.instructor_client.chat.completions.create = MagicMock(
        side_effect=Exception("Stage 1 Forced Parse Failure")
    )

    # Mock Stage 2 reflection returning valid repaired JSON
    mock_choice = MagicMock()
    mock_choice.message.content = """
    {
        "invoice_number": "INV-HEALED",
        "vendor_name": "Repaired Corp",
        "invoice_date": "2024-10-15",
        "currency": "USD",
        "line_items": [{"description": "Repair Item", "quantity": 2, "unit_price": 25.0, "line_total": 50.0}],
        "subtotal": 50.0,
        "tax_amount": 5.0,
        "total_amount": 55.0
    }
    """
    mock_response = MagicMock(choices=[mock_choice])
    extractor.raw_client.chat.completions.create = MagicMock(return_value=mock_response)

    res = extractor.extract_with_retry("Mock OCR text", max_retries=2, enable_reflection=True)
    assert res.execution_status == "REPAIRED_VIA_REFLECTION"
    assert res.attempts_used == 2
    assert res.validated_data.invoice_number == "INV-HEALED"


def test_dlq_routing_on_terminal_failure():
    extractor = SchemaExtractor(api_key="mock-key")

    extractor.instructor_client.chat.completions.create = MagicMock(side_effect=Exception("Terminal Failure"))
    extractor.raw_client.chat.completions.create = MagicMock(side_effect=Exception("Reflection Exhausted"))

    res = extractor.extract_with_retry("Corrupted unparseable scan", max_retries=2)
    assert res.execution_status == "DLQ_FAILED"
    assert res.validated_data is None
    assert any("DLQ" in log for log in res.error_log)

    import json
    from pathlib import Path
    import pytest
    from pydantic import ValidationError
    from src.schemas import InvoiceExtraction

    def test_dlq_manual_resolution_flow(tmp_path: Path):
        """
        Simulates the DLQ resolution lifecycle:
        1. Asserts a captured DLQ failure payload fails Pydantic v2 validation.
        2. Applies operator corrections to resolve math/schema errors.
        3. Validates the corrected payload against InvoiceExtraction.
        4. Confirms active file removal and archive persistence in dlq/resolved/.
        """
        dlq_dir = tmp_path / "dlq"
        resolved_dir = dlq_dir / "resolved"
        dlq_dir.mkdir(parents=True, exist_ok=True)
        resolved_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create a simulated DLQ incident with a mathematical discrepancy
        incident_file = dlq_dir / "dlq_failure_simulated.json"
        broken_payload = {
            "invoice_number": "INV-DLQ-100",
            "vendor_name": "Industrial Fasteners Ltd",
            "invoice_date": "2024-10-15",
            "currency": "USD",
            "line_items": [
                {"description": "Titanium Bolts", "quantity": 10, "unit_price": 5.0, "line_total": 50.0}
            ],
            "subtotal": 50.0,
            "tax_amount": 5.0,
            "total_amount": 999.0,  # Cross-field violation: 50.0 + 5.0 != 999.0
        }
        incident_record = {
            "timestamp": 1729648210,
            "raw_input_snippet": "INVOICE #INV-DLQ-100 ... Total: $999.00",
            "failed_payload": broken_payload,
            "error_trace": ["Reconciliation error: Line items + tax != total"],
            "status": "UNRESOLVED_DLQ",
        }
        incident_file.write_text(json.dumps(incident_record), encoding="utf-8")

        # 2. Ingest incident from disk; assert base payload is rejected by Pydantic
        raw_saved = json.loads(incident_file.read_text(encoding="utf-8"))
        with pytest.raises(ValidationError) as exc_info:
            InvoiceExtraction.model_validate(raw_saved["failed_payload"])
        assert "Reconciliation error" in str(exc_info.value)

        # 3. Simulate operator correction (rectify total_amount to match subtotal + tax)
        corrected_payload = dict(raw_saved["failed_payload"])
        corrected_payload["total_amount"] = 55.0

        # 4. Enforce Pydantic validation gate on rectified payload
        validated_model = InvoiceExtraction.model_validate(corrected_payload)
        assert validated_model.total_amount == 55.0
        assert validated_model.currency == "USD"

        # 5. Execute file migration: archive to resolved/ and unmount from active queue
        raw_saved["failed_payload"] = validated_model.model_dump(mode="json")
        raw_saved["status"] = "MANUALLY_RESOLVED"

        resolved_target = resolved_dir / incident_file.name
        resolved_target.write_text(json.dumps(raw_saved, indent=2), encoding="utf-8")
        incident_file.unlink(missing_ok=True)

        # Verify queue filesystem state
        assert not incident_file.exists(), "Active incident was not purged from unresolved queue"
        assert resolved_target.exists(), "Resolved record was not persisted to resolved directory"

        archived_data = json.loads(resolved_target.read_text(encoding="utf-8"))
        assert archived_data["status"] == "MANUALLY_RESOLVED"
        assert archived_data["failed_payload"]["total_amount"] == 55.0
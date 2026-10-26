# tests/test_extraction.py
import pytest
from pydantic import ValidationError
from src.schemas import InvoiceExtraction, LineItem


def test_golden_document_parsing():
    valid_payload = {
        "invoice_number": "INV-2024-001",
        "vendor_name": "Apex Industrial",
        "invoice_date": "2024-10-15",
        "currency": "USD",
        "line_items": [
            {"description": "Bearing Unit", "quantity": 2, "unit_price": 50.0, "line_total": 100.0}
        ],
        "subtotal": 100.0,
        "tax_amount": 10.0,
        "total_amount": 110.0,
    }
    record = InvoiceExtraction.model_validate(valid_payload)
    assert record.invoice_number == "INV-2024-001"
    assert record.total_amount == 110.0


def test_schema_rejects_negative_quantity():
    with pytest.raises(ValidationError) as exc:
        LineItem(description="Gasket", quantity=-1, unit_price=10.0, line_total=-10.0)
    assert "Input should be greater than 0" in str(exc.value)


def test_cross_field_reconciliation_failure():
    mismatched_payload = {
        "invoice_number": "INV-ERR-002",
        "vendor_name": "Apex Industrial",
        "invoice_date": "2024-10-15",
        "currency": "USD",
        "line_items": [
            {"description": "Bearing Unit", "quantity": 1, "unit_price": 50.0, "line_total": 50.0}
        ],
        "subtotal": 50.0,
        "tax_amount": 5.0,
        "total_amount": 99.0,  # 50 + 5 != 99
    }
    with pytest.raises(ValidationError) as exc:
        InvoiceExtraction.model_validate(mismatched_payload)
    assert "Reconciliation error" in str(exc.value)
from datetime import date
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class LineItem(BaseModel):
    description: str = Field(description="Description of the billable line item")
    quantity: int = Field(default=1, ge=1, description="Item quantity (>= 1)")
    unit_price: float = Field(ge=0.0, description="Unit price (>= 0.0)")
    line_total: float = Field(ge=0.0, description="Total for line item (>= 0.0)")

    @field_validator("quantity", "unit_price", "line_total")
    @classmethod
    def must_be_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Numeric values must be non-negative")
        return v


class InvoiceExtraction(BaseModel):
    invoice_number: str = Field(description="Invoice identification code or number")
    vendor_name: str = Field(description="Name of supplier, seller, or vendor")
    invoice_date: date = Field(
        description="Date the invoice was issued (YYYY-MM-DD)",
        validation_alias=Field.validation_alias if hasattr(Field, "validation_alias") else None,
    )
    currency: str = Field(default="USD", description="3-letter ISO currency code, e.g., USD, EUR")
    line_items: List[LineItem] = Field(default_factory=list, description="Extracted line items")
    subtotal: float = Field(ge=0.0, description="Subtotal before taxes/discounts")
    tax_amount: float = Field(default=0.0, ge=0.0, description="Taxes applied")
    total_amount: float = Field(ge=0.0, description="Grand total payable")

    @model_validator(mode="before")
    @classmethod
    def alias_date_keys(cls, data: dict):
        if isinstance(data, dict):
            # Map alternate date keys produced by LLMs
            if "invoice_date" not in data or not data["invoice_date"]:
                for alt_key in ["issue_date", "date", "billing_date", "inv_date"]:
                    if alt_key in data and data[alt_key]:
                        data["invoice_date"] = data[alt_key]
                        break
        return data

    @model_validator(mode="after")
    def reconcile_math(self) -> "InvoiceExtraction":
        tolerance = 0.05
        calc_subtotal = sum(item.line_total for item in self.line_items)

        # Check subtotal matching line items if line items exist
        if self.line_items and abs(calc_subtotal - self.subtotal) > tolerance:
            # Auto-align subtotal if off by a rounding margin
            self.subtotal = round(calc_subtotal, 2)

        expected_total = self.subtotal + self.tax_amount
        if abs(expected_total - self.total_amount) > tolerance:
            raise ValueError(
                f"Reconciliation error: Line items subtotal ({self.subtotal}) + tax ({self.tax_amount}) = "
                f"{expected_total:.2f}, but grand total was {self.total_amount} (discrepancy exceeds tolerance {tolerance})."
            )
        return self


class ExtractionResult(BaseModel):
    validated_data: Optional[InvoiceExtraction] = None
    raw_payload: Optional[dict] = None
    attempts_used: int = 1
    error_log: List[str] = Field(default_factory=list)
    execution_status: str
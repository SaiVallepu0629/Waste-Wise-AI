from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InventoryItemFields(BaseModel):
    product_name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=0)
    price: float = Field(ge=0, allow_inf_nan=False)
    stock_date: date
    expiry_date: date
    estimated_daily_demand: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )

    @field_validator("product_name", "category")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field must not be blank.")
        return value

    @model_validator(mode="after")
    def expiry_must_not_precede_stock(self):
        if self.expiry_date < self.stock_date:
            raise ValueError("Expiry date must be on or after the stock date.")
        return self


class InventoryItemCreate(InventoryItemFields):
    pass


class InventoryItemUpdate(InventoryItemFields):
    pass


class InventoryItemRead(InventoryItemFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inventory_status: str
    source_type: str
    source_batch_id: int | None
    source_product_id: int | None
    snapshot_date: date | None
    created_at: datetime
    updated_at: datetime


class InventoryItemList(BaseModel):
    items: list[InventoryItemRead]
    total: int
    limit: int
    offset: int


class RuleBasedRecommendation(BaseModel):
    item_id: int
    product_name: str
    quantity: int
    days_to_expiry: int
    rule_based_risk_score: int
    risk_level: str
    likely_to_expire_unsold: bool | None
    quantity_at_risk: float | None
    recommended_discount_pct: int | None
    estimated_surplus_units: float | None
    basis: str

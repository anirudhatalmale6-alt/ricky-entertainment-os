"""Monthly entertainment-budget schemas ("perfil de presupuesto")."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PropertyBudgetIn(BaseModel):
    """Upsert one month of a property's entertainment budget + occupancy."""
    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    entertainment_budget: float = Field(ge=0)
    currency: str = "MXN"
    occupancy_pct: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = None

    @model_validator(mode="after")
    def _round(self):
        self.entertainment_budget = round(self.entertainment_budget, 2)
        if self.occupancy_pct is not None:
            self.occupancy_pct = round(self.occupancy_pct, 2)
        return self


class PropertyBudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    year: int
    month: int
    entertainment_budget: float
    currency: str
    occupancy_pct: float | None = None
    notes: str | None = None
    created_at: datetime

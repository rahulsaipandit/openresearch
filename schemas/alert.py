"""Pydantic schemas for stock price alerts (docs/researchStockSolutions.md)."""

from typing import Literal, Optional
from pydantic import BaseModel


class PriceAlert(BaseModel):
    id: str
    ticker: str
    condition: Literal["ABOVE", "BELOW"]
    target_price: float
    created_at: str
    active: bool = True
    triggered: bool = False
    triggered_at: Optional[str] = None
    triggered_price: Optional[float] = None

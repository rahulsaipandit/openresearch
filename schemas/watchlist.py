"""Pydantic schemas for the stock watchlist (up to 20 tickers)."""

from typing import Optional
from pydantic import BaseModel


class WatchlistItem(BaseModel):
    ticker: str
    added_at: str
    notes: Optional[str] = None

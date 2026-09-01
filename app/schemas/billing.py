"""Shared billing data contracts independent of any worker runtime."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ChargeResult:
    charge_id: str
    user_id: int
    amount: Decimal
    status: str

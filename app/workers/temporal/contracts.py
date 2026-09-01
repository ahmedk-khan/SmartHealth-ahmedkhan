"""Data contracts for Temporal activities.

These are serializable input/output types passed between workflows and activities.
They use Python dataclasses for type safety and JSON serialization.
"""

from dataclasses import dataclass


@dataclass
class ReservationInput:
    """Input to reserve_slot_activity."""
    slot_id: int
    user_id: int


@dataclass
class ReservationResult:
    """Output from reserve_slot_activity and release_slot_activity."""
    slot_id: int
    user_id: int | None
    status: str


@dataclass
class ChargeInput:
    """Input to charge_activity."""
    user_id: int
    amount: float


@dataclass
class ChargeResult:
    """Output from charge_activity and refund_activity."""
    charge_id: str
    user_id: int
    amount: float
    status: str


@dataclass
class ConfirmationInput:
    """Input to send_confirmation_activity."""
    user_id: int
    appointment_id: int

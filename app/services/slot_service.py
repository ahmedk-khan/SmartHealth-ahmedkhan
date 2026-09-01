from app.core.authorization import authorize, Permission
from app.core.exceptions import not_found_error, ConflictError
from app.models import SlotStatus, User, UserRole
from app.repositories import ProviderRepository, SlotRepository, SchedulingRepository
from app.services.base import BaseService


class SlotService(BaseService):
    """Service layer for slot read operations with role-based visibility enforcement."""

    def __init__(self, db):
        super().__init__(db)
        self.repository = SlotRepository(db)
        self.providers = ProviderRepository(db)

    def _available_only(self, current_user: User) -> bool:
        """Patients see only AVAILABLE slots; staff/providers see all."""
        return current_user.role == UserRole.patient

    def get_slot(self, slot_id: int, current_user: User):
        """Fetch a single slot by ID, enforcing visibility rules."""
        authorize(current_user, Permission.SLOT_READ)
        slot = self.repository.get_by_id(slot_id)
        if not slot:
            raise not_found_error("Slot not found")
        # Patients may only view AVAILABLE slots
        if self._available_only(current_user) and slot.status != SlotStatus.AVAILABLE:
            raise not_found_error("Slot not found")
        self.log_info(
            "Slot fetched",
            operation="get_slot",
            data={"slot_id": slot_id, "role": current_user.role},
        )
        return slot

    def list_slots(self, offset: int, limit: int, current_user: User):
        """Return paginated list of slots with patient visibility enforcement."""
        authorize(current_user, Permission.SLOT_READ)
        items, total = self.repository.list_slots(
            offset=offset,
            limit=limit,
            patient_only_available=self._available_only(current_user),
        )
        self.log_info("Slots listed", operation="list_slots", data={"total": total})
        return items, total

    def list_slots_by_provider(
        self,
        provider_id: int,
        offset: int,
        limit: int,
        current_user: User,
    ):
        """
        Return paginated slots for a specific provider.
        - Providers: only own slots.
        - Patients: AVAILABLE only.
        - Admin / front_desk: all.
        """
        authorize(current_user, Permission.SLOT_READ)

        # Providers can only browse their own slots
        if current_user.role == UserRole.provider:
            provider = self.providers.get_by_user_id(current_user.id)
            if not provider or provider.id != provider_id:
                raise not_found_error("Provider not found or access denied")

        items, total = self.repository.list_by_provider(
            provider_id=provider_id,
            offset=offset,
            limit=limit,
            available_only=self._available_only(current_user),
        )
        self.log_info(
            "Slots listed by provider",
            operation="list_slots_by_provider",
            data={"provider_id": provider_id, "total": total},
        )
        return items, total

    def list_slots_by_service(
        self,
        service_id: int,
        offset: int,
        limit: int,
        current_user: User,
    ):
        """Return paginated slots for a specific service with visibility enforcement."""
        authorize(current_user, Permission.SLOT_READ)
        items, total = self.repository.list_by_service(
            service_id=service_id,
            offset=offset,
            limit=limit,
            available_only=self._available_only(current_user),
        )
        self.log_info(
            "Slots listed by service",
            operation="list_slots_by_service",
            data={"service_id": service_id, "total": total},
        )
        return items, total

    # Async methods for Temporal activities (consolidated from workers/temporal/services/scheduling_service.py)
    async def validate_slot_async(self, scheduling_repo: SchedulingRepository, slot_id: int) -> dict[str, int | str]:
        """Validate a slot is available (async for workflow activities)."""
        slot = await scheduling_repo.get_slot(slot_id)
        if slot is None:
            raise not_found_error("Slot not found")
        if slot.status != SlotStatus.AVAILABLE:
            raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE")
        return {"slot_id": slot.id, "status": slot.status.value}

    async def reserve_slot_async(self, scheduling_repo: SchedulingRepository, slot_id: int, user_id: int) -> dict[str, int | str]:
        """Reserve a slot (async for workflow activities)."""
        reserved = await scheduling_repo.reserve_slot(slot_id, user_id)
        if reserved is None:
            raise ConflictError("Slot is no longer available", code="SLOT_NOT_AVAILABLE")
        return {"slot_id": slot_id, "user_id": user_id, "status": reserved.status.value}

    async def release_slot_async(self, scheduling_repo: SchedulingRepository, slot_id: int) -> dict[str, int | str]:
        """Release a reserved slot (async for workflow activities)."""
        released = await scheduling_repo.release_slot(slot_id)
        if released is None:
            raise not_found_error("Reserved slot not found")
        return {"slot_id": slot_id, "user_id": released.patient_id or 0, "status": released.status.value}

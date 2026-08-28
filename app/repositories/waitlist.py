from app.models import WaitlistEntry, WaitlistStatus
from app.repositories.base import BaseRepository


class WaitlistRepository(BaseRepository):
    def get_by_slot_and_patient(self, slot_id: int, patient_id: int) -> WaitlistEntry | None:
        return self.db.query(WaitlistEntry).filter(
            WaitlistEntry.slot_id == slot_id,
            WaitlistEntry.patient_id == patient_id,
        ).order_by(WaitlistEntry.created_at.desc(), WaitlistEntry.id.desc()).first()

    def join(self, slot_id: int, patient_id: int) -> WaitlistEntry:
        entry = self.get_by_slot_and_patient(slot_id, patient_id)
        if entry:
            if entry.status != WaitlistStatus.WAITING:
                entry.status = WaitlistStatus.WAITING
                self.save_and_refresh(entry)
            return entry

        entry = WaitlistEntry(slot_id=slot_id, patient_id=patient_id, status=WaitlistStatus.WAITING)
        self.save_and_refresh(entry)
        return entry

from app.core.exceptions import AppError
from app.models import Appointment
from app.services.base import BaseService


class NotificationService(BaseService):
    def send_appointment_reminder(self, appointment_id: int) -> dict[str, object]:
        appointment = self.db.query(Appointment).filter(Appointment.id == appointment_id).one_or_none()
        if appointment is None:
            raise AppError("Appointment not found", status_code=404, error_type="not_found")

        return {
            "appointment_id": appointment.id,
            "patient_id": appointment.patient_id,
            "provider_id": appointment.provider_id,
            "status": "sent",
            "channel": "email",
        }

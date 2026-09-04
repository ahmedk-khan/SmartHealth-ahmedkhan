"""Unit tests for appointment saga service and Celery task helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.services.appointment_saga_service import AppointmentSagaService
from app.workers.celery.task_helpers import run_notification_task


def test_validate_booking_rejects_missing_patient():
    db = MagicMock()
    service = AppointmentSagaService(db)
    service.patients.get_by_id = MagicMock(return_value=None)

    with pytest.raises(NotFoundError, match="Patient not found"):
        service.validate_booking({"patient_id": 1, "slot_id": 2})


def test_validate_booking_rejects_unavailable_slot():
    db = MagicMock()
    service = AppointmentSagaService(db)
    service.patients.get_by_id = MagicMock(return_value=SimpleNamespace(id=1))
    service.slots.get_by_id = MagicMock(return_value=SimpleNamespace(id=2, status="RESERVED", provider_id=3, service_id=4))

    from app.models import SlotStatus

    slot = service.slots.get_by_id.return_value
    slot.status = SlotStatus.RESERVED

    with pytest.raises(ConflictError, match="Slot is no longer available"):
        service.validate_booking({"patient_id": 1, "slot_id": 2})


def test_run_notification_task_records_success():
    task = SimpleNamespace(
        request=SimpleNamespace(id="task-1", retries=0),
        name="test.notification",
        max_retries=3,
        retry=MagicMock(),
    )

    with patch("app.workers.celery.task_helpers.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        with patch("app.workers.celery.task_helpers.record_celery_task"):
            result = run_notification_task(
                task,
                appointment_id=42,
                metric_name="test_notification",
                handler=lambda db: {"appointment_id": 42, "status": "sent"},
            )

    assert result == {"appointment_id": 42, "status": "sent"}
    mock_db.close.assert_called_once()

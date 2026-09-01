"""
Patient context service for PHI-scoped retrieval.

Provides patient-specific information (appointments, history) with strict PHI filtering.
A patient can only see their own data; cross-patient data access is prevented at query level.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models import User, UserRole, Patient, Appointment, AppointmentStatus

logger = logging.getLogger(__name__)


def get_patient_context(db: Session, current_user: User) -> Optional[dict]:
    """
    Get PHI-scoped patient context.
    
    Requirement: A patient can only access their own data. This is enforced
    at the query level (not in application logic or prompt).
    
    Args:
        db: Database session
        current_user: Authenticated user
    
    Returns:
        Dictionary with patient's appointment history, or None if not a patient
    
    Security Note:
        - Query filters by patient_id = current_user.patient.id
        - No cross-patient data possible
        - Test verifies patient A cannot see patient B's appointments
    """
    if current_user.role != UserRole.patient:
        return None
    
    # Get patient relationship
    patient = current_user.patient
    if not patient:
        return None
    
    # Query appointments for THIS patient only (PHI scoping)
    appointments = db.query(Appointment).filter(
        Appointment.patient_id == patient.id  # ← Security: This patient only
    ).order_by(Appointment.created_at.desc()).limit(10).all()
    
    if not appointments:
        return None
    
    # Summarize for context (not exposing full details to LLM)
    context = {
        "patient_id": patient.id,
        "appointment_count": len(appointments),
        "recent_appointments": [
            {
                "service_id": apt.service_id,
                "service_name": apt.service.name,
                "status": apt.status.value,
                "booked_at": apt.booked_at.isoformat() if apt.booked_at else None,
            }
            for apt in appointments[:3]  # Most recent 3
        ],
        "active_appointments": [
            {
                "service_id": apt.service_id,
                "service_name": apt.service.name,
                "status": apt.status.value,
            }
            for apt in appointments
            if apt.status in (AppointmentStatus.SLOT_RESERVED, AppointmentStatus.CONFIRMED)
        ],
    }
    
    return context


def get_patient_id_or_none(current_user: User) -> Optional[int]:
    """
    Get patient ID if user is authenticated as patient, else None.
    
    Used for PHI-scoped queries.
    """
    if current_user.role == UserRole.patient and current_user.patient:
        return current_user.patient.id
    return None


def verify_patient_access(db: Session, current_user: User, patient_id: int) -> bool:
    """
    Verify that current_user can access patient_id's data.
    
    Security requirement: Prevent cross-patient access.
    
    Args:
        db: Database session
        current_user: Authenticated user
        patient_id: Patient ID being accessed
    
    Returns:
        True if current_user can access patient_id, False otherwise
    """
    # Admins can see any patient
    if current_user.role == UserRole.admin:
        return True
    
    # Patients can only see their own data
    if current_user.role == UserRole.patient:
        return current_user.patient and current_user.patient.id == patient_id
    
    # Other roles (provider, front_desk) don't have direct patient access via search
    return False

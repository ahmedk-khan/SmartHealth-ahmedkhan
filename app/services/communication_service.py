"""
Communication & Report Generation Service

Handles:
- Patient-facing appointment summaries
- Follow-up communication drafts
- Department utilisation reports

All outputs are grounded in real data from appointments and analytics tables.
Generated content is saved with prompt version for reproducibility.
"""

import json
import asyncio
from datetime import datetime, date
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.logging import get_correlation_id
from app.core.settings import settings
from app.models import User, Appointment, GeneratedContent, AnalyticsDaily, UserRole
from app.repositories.analytics import AnalyticsRepository
from app.schemas.assistant import (
    AppointmentSummary,
    AppointmentFollowup,
    UtilisationReport,
    GeneratedContentMetadata,
    ReportGenerationResponse,
)
from app.services.llm_provider import LLMProvider
from app.services.assistant_prompts import PROMPT_REPORT_V1

PROMPT_VERSION_COMMUNICATION = "PROMPT_COMMUNICATION_V1"
MAX_GENERATED_TEXT_LENGTH = 4000
UNSAFE_GENERATED_TERMS = ("diagnose", "diagnosis", "treatment", "prescribe", "prescription", "medication dosage")


class CommunicationService:
    """Service for generating summaries, follow-ups, and reports."""
    
    def __init__(self, db: Session, provider: LLMProvider):
        self.db = db
        self.provider = provider
        self.analytics = AnalyticsRepository(db)
    
    # ─────────────────────────────────────────────────────────────
    # Appointment Summaries (Patient-Facing)
    # ─────────────────────────────────────────────────────────────
    
    async def generate_appointment_summary(
        self,
        appointment_id: int,
        current_user: User,
        include_instructions: bool = True,
        include_cancellation_policy: bool = True,
    ) -> tuple[AppointmentSummary, GeneratedContentMetadata]:
        """
        Generate patient-facing appointment summary.
        
        Grounding: All data pulled from Appointment, Provider, Service, Slot models.
        No invented data.
        
        Returns: (AppointmentSummary, GeneratedContentMetadata)
        """
        # Fetch appointment with all related data
        appointment = await asyncio.to_thread(
            lambda: self.db.query(Appointment).filter(Appointment.id == appointment_id).first()
        )
        
        if not appointment:
            raise AppError(
                f"Appointment {appointment_id} not found",
                status_code=404,
                error_type="not_found",
                code="APPOINTMENT_NOT_FOUND",
            )
        
        # Auth check: current user can only generate summaries for their own appointments
        # or if staff/admin
        if not self._user_can_access_appointment(current_user, appointment):
            raise AppError(
                "Unauthorized access to appointment",
                status_code=403,
                error_type="forbidden",
                code="FORBIDDEN",
            )
        
        # Extract real data from database
        provider_name = self._display_name(appointment.provider.user, "Provider")
        service_name = appointment.service.name
        slot = appointment.slot
        appointment_date = slot.start_datetime.strftime("%B %d, %Y") if slot else "TBD"
        appointment_time = slot.start_datetime.strftime("%H:%M UTC") if slot else "TBD"
        location = "Clinic"
        
        # Build prompt with real data (grounding)
        prompt_data = {
            "provider_name": provider_name,
            "service_name": service_name,
            "appointment_date": appointment_date,
            "appointment_time": appointment_time,
            "location": location,
            "service_description": appointment.service.description or "",
        }
        
        prompt = self._build_summary_prompt(prompt_data, include_instructions, include_cancellation_policy)
        
        # Call LLM
        summary_text = await self.provider.complete(prompt)
        self._validate_generated_text(summary_text)
        
        # Extract pre-visit instructions if requested
        pre_visit_instructions = None
        if include_instructions:
            pre_visit_instructions = self._extract_section(summary_text, "instructions")
        
        # Extract cancellation policy if requested
        cancellation_policy = None
        if include_cancellation_policy:
            cancellation_policy = self._extract_section(summary_text, "cancellation")
        
        # Build response
        summary = AppointmentSummary(
            appointment_id=appointment_id,
            summary=summary_text,
            provider_name=provider_name,
            service_name=service_name,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            location=location,
            pre_visit_instructions=pre_visit_instructions,
            cancellation_policy=cancellation_policy,
        )
        
        # Save to database
        metadata = await self._save_generated_content(
            appointment_id=appointment_id,
            content_type="summary",
            content=summary.model_dump(),
            initiated_by_user_id=current_user.id,
        )
        
        return summary, metadata
    
    # ─────────────────────────────────────────────────────────────
    # Follow-up Communications (Staff Draft)
    # ─────────────────────────────────────────────────────────────
    
    async def generate_appointment_followup(
        self,
        appointment_id: int,
        current_user: User,
        tone: str = "professional",
        include_next_steps: bool = True,
    ) -> tuple[AppointmentFollowup, GeneratedContentMetadata]:
        """
        Generate follow-up communication draft.
        
        Grounding: All data pulled from Appointment, Visit, Patient models.
        No invented diagnoses or medical details.
        
        Returns: (AppointmentFollowup, GeneratedContentMetadata)
        """
        # Fetch appointment
        appointment = await asyncio.to_thread(
            lambda: self.db.query(Appointment).filter(Appointment.id == appointment_id).first()
        )
        
        if not appointment:
            raise AppError(
                f"Appointment {appointment_id} not found",
                status_code=404,
                error_type="not_found",
                code="APPOINTMENT_NOT_FOUND",
            )
        
        # Auth check: staff/admin only
        if not self._user_is_staff(current_user):
            raise AppError(
                "Only staff can generate follow-ups",
                status_code=403,
                error_type="forbidden",
                code="FORBIDDEN",
            )
        
        # Extract real data
        provider_name = self._display_name(appointment.provider.user, "Provider")
        service_name = appointment.service.name
        patient_name = self._display_name(appointment.patient, "Patient")
        appointment_date = appointment.slot.start_datetime.strftime("%B %d, %Y") if appointment.slot else "N/A"
        visit_completed = appointment.visit is not None
        
        # Build prompt with real data
        prompt_data = {
            "provider_name": provider_name,
            "service_name": service_name,
            "patient_name": patient_name,
            "appointment_date": appointment_date,
            "visit_completed": visit_completed,
            "tone": tone,
        }
        
        prompt = self._build_followup_prompt(prompt_data, include_next_steps)
        
        # Call LLM
        followup_text = await self.provider.complete(prompt)
        self._validate_generated_text(followup_text)

        # Parse response
        subject = self._extract_subject(followup_text)
        body = self._extract_body(followup_text)
        recommended_channel = self._determine_channel(appointment_date, visit_completed)
        follow_up_actions = self._extract_actions(followup_text) if include_next_steps else []
        
        # Build response
        followup = AppointmentFollowup(
            appointment_id=appointment_id,
            subject=subject,
            body=body,
            recommended_channel=recommended_channel,
            follow_up_actions=follow_up_actions,
            requires_review=True,  # Staff must review before sending
        )
        
        # Save to database
        metadata = await self._save_generated_content(
            appointment_id=appointment_id,
            content_type="followup",
            content=followup.model_dump(),
            initiated_by_user_id=current_user.id,
        )
        
        return followup, metadata
    
    # ─────────────────────────────────────────────────────────────
    # Utilisation Reports (Real Analytics Data)
    # ─────────────────────────────────────────────────────────────
    
    async def generate_utilisation_report(
        self,
        period_start: date,
        period_end: date,
        current_user: User,
    ) -> ReportGenerationResponse:
        """
        Generate department utilisation report.
        
        Grounding: ALL numbers come directly from analytics_daily table.
        No invented or estimated numbers.
        
        Returns: ReportGenerationResponse with real data
        """
        # Auth check: front desk and admin can generate utilisation reports
        if not self._user_is_staff(current_user):
            raise AppError(
                "Only front desk or admin can generate utilisation reports",
                status_code=403,
                error_type="forbidden",
                code="FORBIDDEN",
            )
        
        # Fetch real analytics data
        values = await asyncio.to_thread(
            self.analytics.dashboard_rollup_metrics,
            period_start.isoformat(),
            period_end.isoformat(),
        )
        
        if values is None:
            values = {
                "appointments_total": 0,
                "completed_visits_total": 0,
                "cancelled_appointments_total": 0,
                "patients_total": 0,
                "failed_workflows_total": 0,
            }
        
        # Create report with real data
        report = UtilisationReport(
            period_start=period_start,
            period_end=period_end,
            appointments_booked=values["appointments_total"],
            completed_visits=values["completed_visits_total"],
            cancellations=values["cancelled_appointments_total"],
            total_patients=values["patients_total"],
            failed_workflows=values["failed_workflows_total"],
        )
        
        # Save to database
        metadata = await self._save_generated_content(
            content_type="utilisation_report",
            content=report.model_dump(),
            report_scope=f"{period_start.isoformat()}_to_{period_end.isoformat()}",
            initiated_by_user_id=current_user.id,
        )
        
        return ReportGenerationResponse(
            report=report,
            metadata=metadata,
        )
    
    # ─────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _display_name(entity, fallback: str) -> str:
        """Return the model's available display name without exposing email addresses."""
        full_name = getattr(entity, "full_name", None)
        if full_name:
            return full_name.strip()
        first_name = getattr(entity, "first_name", None) or ""
        last_name = getattr(entity, "last_name", None) or ""
        name = f"{first_name} {last_name}".strip()
        return name or fallback
    
    async def _save_generated_content(
        self,
        content_type: str,
        content: dict,
        appointment_id: Optional[int] = None,
        report_scope: Optional[str] = None,
        initiated_by_user_id: Optional[int] = None,
    ) -> GeneratedContentMetadata:
        """Save generated content to database with metadata."""
        generated = GeneratedContent(
            appointment_id=appointment_id,
            initiated_by_user_id=initiated_by_user_id,
            correlation_id=get_correlation_id(),
            report_scope=report_scope,
            type=content_type,
            content=content,
            model=settings.llm_model,
            prompt_version=PROMPT_VERSION_COMMUNICATION,
        )
        self.db.add(generated)
        self.db.commit()
        self.db.refresh(generated)
        
        return GeneratedContentMetadata(
            id=generated.id,
            type=content_type,
            appointment_id=appointment_id,
            report_scope=report_scope,
            model=settings.llm_model,
            prompt_version=PROMPT_VERSION_COMMUNICATION,
            created_at=generated.created_at.isoformat(),
        )
    
    def _build_summary_prompt(self, data: dict, include_instructions: bool, include_policy: bool) -> str:
        """Build prompt for appointment summary generation."""
        prompt = f"""You are a healthcare communication specialist.
        
Generate a patient-friendly appointment summary with the following information:
- Provider: {data['provider_name']}
- Service: {data['service_name']}
- Date: {data['appointment_date']}
- Time: {data['appointment_time']}
- Location: {data['location']}
- Description: {data['service_description']}

Create a clear, warm, and professional summary that:
1. Confirms the appointment details
2. Welcomes the patient
3. Sets expectations for the visit"""
        
        if include_instructions:
            prompt += "\n4. Provides pre-visit instructions (if applicable)"
        
        if include_policy:
            prompt += "\n5. Includes cancellation policy (24-hour notice required)"
        
        prompt += "\n\nKeep the tone friendly and supportive."
        return prompt

    def _validate_generated_text(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned or len(cleaned) > MAX_GENERATED_TEXT_LENGTH:
            raise AppError("Generated content failed length validation", status_code=502, error_type="generated_content_invalid", code="GENERATED_CONTENT_INVALID")
        lowered = cleaned.casefold()
        if any(term in lowered for term in UNSAFE_GENERATED_TERMS):
            raise AppError("Generated content failed safety validation", status_code=502, error_type="generated_content_unsafe", code="GENERATED_CONTENT_UNSAFE")
        return cleaned

    def _restore_prompt_tokens(self, text: str, replacements: dict[str, str]) -> str:
        """Restore legacy prompt tokens for callers that still use the helper."""
        for token, value in replacements.items():
            text = text.replace(token, value)
        return text

    def _build_followup_prompt(self, data: dict, include_next_steps: bool) -> str:
        """Build prompt for follow-up communication generation."""
        prompt = f"""You are a healthcare communication specialist.

Generate a follow-up communication draft for a patient after their appointment.

Details:
- Provider: {data['provider_name']}
- Service: {data['service_name']}
- Patient: {data['patient_name']}
- Appointment Date: {data['appointment_date']}
- Visit Completed: {data['visit_completed']}
- Tone: {data['tone']}

Create a professional follow-up message that:
1. Thanks the patient for visiting
2. Provides appointment summary
3. Addresses any immediate concerns"""
        
        if include_next_steps:
            prompt += "\n4. Recommends next steps if applicable"
        
        prompt += "\n\nInclude a subject line and main body."
        prompt += "\nDo NOT invent medical information. Reference only the visit that occurred."
        
        return prompt
    
    def _extract_section(self, text: str, section_name: str) -> Optional[str]:
        """Extract a section from generated text."""
        lines = text.split("\n")
        in_section = False
        section_lines = []
        
        for line in lines:
            lower = line.lower()
            if section_name in lower:
                in_section = True
                continue
            if in_section:
                if line.startswith("#") or line.startswith("---"):
                    break
                if line.strip():
                    section_lines.append(line)
        
        return "\n".join(section_lines).strip() if section_lines else None
    
    def _extract_subject(self, text: str) -> str:
        """Extract subject line from follow-up text."""
        lines = text.split("\n")
        for line in lines:
            if "subject:" in line.lower():
                return line.split(":", 1)[1].strip()
        return "Appointment Follow-up"
    
    def _extract_body(self, text: str) -> str:
        """Extract body from follow-up text."""
        lines = text.split("\n")
        body_lines = []
        in_body = False
        
        for line in lines:
            if "body:" in line.lower():
                in_body = True
                continue
            if in_body and line.strip():
                body_lines.append(line)
        
        return "\n".join(body_lines).strip() or text
    
    def _determine_channel(self, appointment_date: str, visit_completed: bool) -> str:
        """Determine recommended communication channel."""
        if visit_completed:
            return "email"  # Post-visit summaries via email
        else:
            return "sms"  # Pre-visit reminders via SMS
    
    def _extract_actions(self, text: str) -> list[str]:
        """Extract recommended follow-up actions from text."""
        actions = []
        lines = text.split("\n")
        in_actions = False
        
        for line in lines:
            if "next steps" in line.lower() or "actions" in line.lower():
                in_actions = True
                continue
            if in_actions and line.strip():
                if line.strip().startswith("-") or line.strip().startswith("•"):
                    actions.append(line.strip().lstrip("-•").strip())
        
        return actions[:5]  # Limit to 5 actions
    
    def _user_can_access_appointment(self, user: User, appointment: Appointment) -> bool:
        """Check if user can access appointment (patient owns it or staff)."""
        if user.role in {UserRole.admin, UserRole.front_desk, UserRole.provider}:
            return True
        if user.role == UserRole.patient:
            patient = getattr(user, "patient", None)
            patient_id = getattr(patient, "id", None)
            return patient_id is not None and patient_id == appointment.patient_id
        return False
    
    def _user_is_staff(self, user: User) -> bool:
        """Check if user is staff or admin."""
        return user.role in {UserRole.admin, UserRole.front_desk, UserRole.provider}
    
    def _user_is_admin(self, user: User) -> bool:
        """Check if user is admin."""
        return user.role == UserRole.admin

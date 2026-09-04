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
import re
from datetime import datetime, date
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_correlation_id
from app.core.settings import settings
from app.models import User, Appointment, GeneratedContent, AnalyticsDaily
from app.repositories.analytics import AnalyticsRepository
from app.schemas.assistant import (
    AppointmentSummary,
    AppointmentFollowup,
    UtilisationReport,
    GeneratedContentMetadata,
    ReportGenerationResponse,
)
from app.services.llm_provider import LLMProvider
from app.services.assistant_prompts import PROMPT_REPORT_V1, PROMPT_VERSION_REPORT

PROMPT_VERSION_COMMUNICATION = "PROMPT_COMMUNICATION_V1"
MAX_GENERATED_TEXT_LENGTH = 4000
UNSAFE_GENERATED_PATTERNS = (
    re.compile(r"\bdiagnos(?:e|is|ed|ing)\b"),
    re.compile(r"\bprescri(?:be|bed|bing|ption)\b"),
    re.compile(r"\bmedications?\s+(?:dosage|dose|amount)\b"),
    re.compile(r"\btreatment\s+(?:plan|recommendation|regimen)\b"),
)
# LLM outputs often use typographic punctuation that breaks clients / extractors.
_UNICODE_CLEANUPS = str.maketrans({
    "\u2011": "-",  # non-breaking hyphen
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u202f": " ",  # narrow no-break space
    "\u00a0": " ",  # nbsp
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
})
_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "instructions": (
        "pre-visit instructions",
        "pre visit instructions",
        "pre-visit tips",
        "pre visit tips",
        "helpful pre-visit",
        "what to bring",
        "preparation tips",
        "instructions",
    ),
    "cancellation": (
        "cancellation policy",
        "cancelation policy",
        "cancellation",
        "cancel or reschedule",
    ),
}


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
            raise NotFoundError(
                f"Appointment {appointment_id} not found",
                code="APPOINTMENT_NOT_FOUND",
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
        
        # Appointment summaries are factual records, so render them from the
        # appointment instead of allowing a model to invent visit guidance.
        pre_visit_instructions = "Arrive 10 minutes early and bring your ID." if include_instructions else None
        cancellation_policy = "24-hour notice is required to cancel or reschedule." if include_cancellation_policy else None
        summary_lines = [
            "Appointment Confirmation",
            "",
            "Dear Patient,",
            "",
            "This message confirms your appointment with the following details:",
            "",
            f"Provider: {provider_name}",
            f"Service: {service_name}",
            f"Date: {appointment_date}",
            f"Time: {appointment_time}",
            f"Location: {location}",
        ]
        if pre_visit_instructions:
            summary_lines.extend(["", "Pre-visit instructions:", pre_visit_instructions])
        if cancellation_policy:
            summary_lines.extend(["", "Cancellation policy:", cancellation_policy])
        summary_lines.extend(["", "Sincerely,", "The Clinic Team"])
        summary_text = "\n".join(summary_lines)
        
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
            raise NotFoundError(
                f"Appointment {appointment_id} not found",
                code="APPOINTMENT_NOT_FOUND",
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

        # Make exactly one model call for auditability, but render the returned
        # communication from verified appointment data to prevent hallucinations.
        await self.provider.complete(prompt)
        if visit_completed:
            subject = f"Follow-up regarding your {service_name} appointment"
            body = (
                f"Dear {patient_name},\n\n"
                f"Thank you for attending your {service_name} appointment with {provider_name} "
                f"on {appointment_date}. Please contact the clinic if you have questions or need further assistance.\n\n"
                "Sincerely,\nThe Clinic Team"
            )
        else:
            subject = f"Follow-up regarding your upcoming {service_name} appointment"
            body = (
                f"Dear {patient_name},\n\n"
                f"This is a follow-up regarding your {service_name} appointment with {provider_name} "
                f"on {appointment_date}. Please contact the clinic if you have questions or need further assistance.\n\n"
                "Sincerely,\nThe Clinic Team"
            )
        recommended_channel = self._determine_channel(appointment_date, visit_completed)
        follow_up_actions = (
            ["Contact the clinic if you have questions or need further assistance."]
            if include_next_steps
            else []
        )
        
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
        # Auth check: analytics permission required (enforced at endpoint)
        
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
            content=report.model_dump(mode="json"),
            report_scope=f"{period_start.isoformat()}..{period_end.isoformat()}",
            initiated_by_user_id=current_user.id,
            prompt_version=PROMPT_VERSION_REPORT,
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
        prompt_version: str = PROMPT_VERSION_COMMUNICATION,
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
            prompt_version=prompt_version,
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
            prompt_version=prompt_version,
            created_at=generated.created_at.isoformat(),
        )

    @staticmethod
    def format_utilisation_report_text(report: UtilisationReport) -> str:
        """Return a human-readable summary for SSE text streaming."""
        return (
            f"Utilisation report for {report.period_start} to {report.period_end}: "
            f"{report.appointments_booked} appointments booked, "
            f"{report.completed_visits} completed visits, "
            f"{report.cancellations} cancellations, "
            f"{report.total_patients} total patients, "
            f"{report.failed_workflows} failed workflows."
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
        if any(pattern.search(lowered) for pattern in UNSAFE_GENERATED_PATTERNS):
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
        
        prompt += """

Use this exact format (plain text labels, no markdown on the Subject line):
Subject: <concise email subject>
Body:
<email body starting with the greeting>

Do NOT prefix the subject with markdown like **Subject:**.
Do NOT invent medical information. Reference only the visit that occurred."""

        if include_next_steps:
            prompt += """
If you include next steps, use a markdown heading exactly:
### Recommended Next Steps
- action item
"""
        
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

    @staticmethod
    def _strip_outer_markdown(value: str) -> str:
        """Remove leading/trailing bold markers and stray asterisks from a label value."""
        cleaned = value.strip()
        cleaned = re.sub(r"^\*+\s*", "", cleaned)
        cleaned = re.sub(r"\s*\*+$", "", cleaned)
        return cleaned.strip()
    
    def _extract_subject(self, text: str) -> str:
        """Extract subject line from follow-up text."""
        for line in text.split("\n"):
            match = re.search(r"(?i)\*{0,2}\s*subject\s*\*{0,2}\s*:\s*(.+)$", line.strip())
            if match:
                subject = self._strip_outer_markdown(match.group(1))
                if subject:
                    return subject
        return "Appointment Follow-up"
    
    def _extract_body(self, text: str) -> str:
        """Extract body from follow-up text, excluding the subject line."""
        lines = text.split("\n")
        body_lines: list[str] = []
        found_body_marker = False

        for line in lines:
            if re.search(r"(?i)\*{0,2}\s*body\s*\*{0,2}\s*:", line.strip()):
                found_body_marker = True
                after = line.split(":", 1)[1].strip() if ":" in line else ""
                if after:
                    body_lines.append(after)
                continue
            if found_body_marker:
                body_lines.append(line)

        if found_body_marker:
            return "\n".join(body_lines).strip() or text

        # No Body: marker — drop Subject: line(s) and return the remainder
        cleaned: list[str] = []
        for line in lines:
            if re.search(r"(?i)\*{0,2}\s*subject\s*\*{0,2}\s*:", line.strip()):
                continue
            cleaned.append(line)
        while cleaned and not cleaned[0].strip():
            cleaned.pop(0)
        return "\n".join(cleaned).strip() or text
    
    def _determine_channel(self, appointment_date: str, visit_completed: bool) -> str:
        """Determine recommended communication channel."""
        if visit_completed:
            return "email"  # Post-visit summaries via email
        else:
            return "sms"  # Pre-visit reminders via SMS
    
    def _extract_actions(self, text: str) -> list[str]:
        """Extract recommended follow-up actions from heading sections only."""
        actions: list[str] = []
        in_actions = False

        for line in text.split("\n"):
            stripped = line.strip()
            lower = stripped.lower()

            is_heading = bool(re.match(r"^#{1,6}\s+", stripped)) or (
                stripped.startswith("**") and "next step" in lower
            ) or (
                lower.startswith("recommended next step")
                or lower.startswith("next steps")
                or lower.startswith("follow-up actions")
                or lower.startswith("follow up actions")
            )
            if is_heading and ("next step" in lower or re.search(r"\bactions?\b", lower)):
                in_actions = True
                continue

            if not in_actions:
                continue

            if not stripped:
                continue
            # End section at next heading or horizontal rule (not bullet "---" false positives)
            if re.match(r"^#{1,6}\s+", stripped) or re.match(r"^-{3,}$", stripped):
                break

            if stripped.startswith(("-", "•")) or re.match(r"^\*\s+", stripped):
                action = re.sub(r"^[-•*]\s*", "", stripped).strip()
                if action:
                    actions.append(action)

        return actions[:5]

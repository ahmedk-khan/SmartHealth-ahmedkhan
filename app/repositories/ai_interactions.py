import logging

from app.models import AIInteraction, Appointment, Patient
from app.repositories.base import BaseRepository
from sqlalchemy import func, inspect
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class AIInteractionRepository(BaseRepository):
    def create_interaction(self, **values) -> AIInteraction:
        interaction = AIInteraction(**values)
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        return interaction

    def summary(self) -> dict[str, object]:
        try:
            if not inspect(self.db.bind).has_table("ai_interactions"):
                return {
                    "questions_asked": 0,
                    "answered_total": 0,
                    "refused_total": 0,
                    "refusal_rate": 0.0,
                    "intent_breakdown": {},
                    "booking_conversions": 0,
                    "booking_conversion_rate": 0.0,
                    "avg_latency_ms": 0.0,
                    "p95_latency_ms": 0,
                    "total_tokens_used": 0,
                    "estimated_cost_total_usd": 0.0,
                    "interactions_total": 0,
                    "appointment_navigation_interactions": 0,
                }

            rows = self.db.query(AIInteraction).all()
        except SQLAlchemyError:
            logger.exception("AI analytics summary failed because the AI interaction table is unavailable")
            return {
                "questions_asked": 0,
                "answered_total": 0,
                "refused_total": 0,
                "refusal_rate": 0.0,
                "intent_breakdown": {},
                "booking_conversions": 0,
                "booking_conversion_rate": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0,
                "total_tokens_used": 0,
                "estimated_cost_total_usd": 0.0,
                "interactions_total": 0,
                "appointment_navigation_interactions": 0,
            }

        total = len(rows)
        refused = sum(1 for row in rows if row.refused)
        answered = sum(1 for row in rows if not row.refused)
        intents = {}
        for row in rows:
            intents[row.intent] = intents.get(row.intent, 0) + 1

        latencies = [row.latency_ms or 0 for row in rows]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        p95_latency = 0
        if latencies:
            sorted_values = sorted(latencies)
            index = max(0, min(len(sorted_values) - 1, int(len(sorted_values) * 0.95) - 1))
            p95_latency = sorted_values[index]

        total_tokens = sum((row.input_tokens or 0) + (row.output_tokens or 0) for row in rows)
        estimated_cost = total_tokens * 0.00001

        appointment_intents = sum(1 for row in rows if row.intent == "appointment")
        appointment_users = self.db.query(AIInteraction.user_id).filter(
            AIInteraction.intent == "appointment",
            AIInteraction.user_id.isnot(None),
        ).distinct().subquery()
        converted = self.db.query(func.count(func.distinct(Appointment.id))).join(
            Patient, Patient.id == Appointment.patient_id,
        ).filter(Patient.user_id.in_(self.db.query(appointment_users.c.user_id))).scalar() or 0

        return {
            "questions_asked": int(total),
            "answered_total": int(answered),
            "refused_total": int(refused),
            "refusal_rate": float(refused / total) if total else 0.0,
            "intent_breakdown": intents,
            "booking_conversions": int(converted),
            "booking_conversion_rate": float(converted / appointment_intents) if appointment_intents else 0.0,
            "avg_latency_ms": float(avg_latency),
            "p95_latency_ms": int(p95_latency),
            "total_tokens_used": int(total_tokens),
            "estimated_cost_total_usd": float(estimated_cost),
            "interactions_total": int(total),
            "appointment_navigation_interactions": int(appointment_intents),
        }

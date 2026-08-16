"""
Event Envelope structures for healthcare domain events.

Provides standardized envelopes for wrapping events with correlation metadata,
ensuring complete traceability across asynchronous boundaries.
"""

from typing import Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from uuid import uuid4

from app.core.logging import get_correlation_id, get_request_id


@dataclass
class EventMetadata:
    """
    Metadata envelope for domain events.
    
    Includes correlation tracking, temporal markers, and source information
    for complete event traceability.
    """
    event_id: str
    event_type: str
    source: str
    occurred_at: str
    schema_version: int = 1
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    workflow_id: Optional[str] = None
    user_id: Optional[int] = None
    
    @classmethod
    def create(
        cls,
        event_type: str,
        source: str = "smarthealth-api",
        workflow_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> "EventMetadata":
        """
        Create event metadata with automatic correlation context.
        
        Args:
            event_type: Type of event (e.g., 'appointment.created')
            source: Source system identifier (default: smarthealth-api)
            workflow_id: Optional Temporal workflow ID
            user_id: Optional user ID for audit trail
        
        Returns:
            EventMetadata instance with auto-captured correlation context
        """
        return cls(
            event_id=str(uuid4()),
            event_type=event_type,
            source=source,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            correlation_id=get_correlation_id(),
            request_id=get_request_id(),
            workflow_id=workflow_id,
            user_id=user_id,
        )


@dataclass
class EventEnvelope:
    """
    Complete event envelope wrapping domain event payload.
    
    Provides a standard structure for all events published to event streams,
    with full correlation tracking for observability.
    """
    metadata: EventMetadata
    data: dict[str, Any]
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert envelope to dictionary for serialization.
        
        Returns:
            Dictionary representation of the complete envelope
        """
        return {
            "metadata": asdict(self.metadata),
            "data": self.data,
        }
    
    @staticmethod
    def create(
        event_type: str,
        data: dict[str, Any],
        source: str = "smarthealth-api",
        workflow_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> "EventEnvelope":
        """
        Create a complete event envelope.
        
        Args:
            event_type: Type of event
            data: Event payload
            source: Source system identifier
            workflow_id: Optional workflow ID
            user_id: Optional user ID
        
        Returns:
            Complete EventEnvelope instance
        """
        metadata = EventMetadata.create(
            event_type=event_type,
            source=source,
            workflow_id=workflow_id,
            user_id=user_id,
        )
        return EventEnvelope(metadata=metadata, data=data)


class EventEnvelopeFactory:
    """
    Factory for creating typed event envelopes.
    
    Provides convenient methods for creating domain-specific events
    with proper structure and correlation context.
    """
    
    @staticmethod
    def create_appointment_event(
        event_type: str,
        appointment_id: int,
        patient_id: Optional[int] = None,
        provider_id: Optional[int] = None,
        service_id: Optional[int] = None,
        slot_id: Optional[int] = None,
        status: Optional[str] = None,
        visit_status: Optional[str] = None,
        workflow_id: Optional[str] = None,
        user_id: Optional[int] = None,
        **extra_data,
    ) -> EventEnvelope:
        """
        Create an appointment domain event.
        
        Args:
            event_type: Type of appointment event
            appointment_id: ID of the appointment
            patient_id: Optional patient ID
            provider_id: Optional provider ID
            service_id: Optional service ID
            slot_id: Optional slot ID
            status: Optional appointment status
            visit_status: Optional visit status
            workflow_id: Optional Temporal workflow ID
            user_id: Optional user ID for audit
            **extra_data: Additional event payload
        
        Returns:
            EventEnvelope for appointment event
        """
        data = {
            "appointment_id": appointment_id,
            "patient_id": patient_id,
            "provider_id": provider_id,
            "service_id": service_id,
            "slot_id": slot_id,
            "status": status,
            "visit_status": visit_status,
            **extra_data,
        }
        
        return EventEnvelope.create(
            event_type=event_type,
            data=data,
            workflow_id=workflow_id,
            user_id=user_id,
        )
    
    @staticmethod
    def create_service_event(
        event_type: str,
        service_id: int,
        department_id: Optional[int] = None,
        status: Optional[str] = None,
        user_id: Optional[int] = None,
        **extra_data,
    ) -> EventEnvelope:
        """
        Create a service domain event.
        
        Args:
            event_type: Type of service event
            service_id: ID of the service
            department_id: Optional department ID
            status: Optional service status
            user_id: Optional user ID for audit
            **extra_data: Additional event payload
        
        Returns:
            EventEnvelope for service event
        """
        data = {
            "service_id": service_id,
            "department_id": department_id,
            "status": status,
            **extra_data,
        }
        
        return EventEnvelope.create(
            event_type=event_type,
            data=data,
            user_id=user_id,
        )
    
    @staticmethod
    def create_billing_event(
        event_type: str,
        billing_id: int,
        appointment_id: int,
        amount: float,
        status: Optional[str] = None,
        user_id: Optional[int] = None,
        **extra_data,
    ) -> EventEnvelope:
        """
        Create a billing domain event.
        
        Args:
            event_type: Type of billing event
            billing_id: ID of the billing record
            appointment_id: ID of the associated appointment
            amount: Billing amount
            status: Optional billing status
            user_id: Optional user ID for audit
            **extra_data: Additional event payload
        
        Returns:
            EventEnvelope for billing event
        """
        data = {
            "billing_id": billing_id,
            "appointment_id": appointment_id,
            "amount": amount,
            "status": status,
            **extra_data,
        }
        
        return EventEnvelope.create(
            event_type=event_type,
            data=data,
            user_id=user_id,
        )

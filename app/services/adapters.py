"""
Adapter interfaces for service layer to abstract worker implementations.

This ensures services remain decoupled from Temporal, Kafka, and Celery specifics,
following clean architecture principles and enabling easy testing/mocking.
"""

from abc import ABC, abstractmethod
from typing import Any
from datetime import timedelta


class WorkflowOrchestratorAdapter(ABC):
    """Abstract interface for workflow orchestration (Temporal)."""
    
    @abstractmethod
    async def start_service_publish_workflow(self, service_id: int, workflow_id: str) -> dict[str, Any]:
        """Start a service publication workflow."""
        raise NotImplementedError
    
    @abstractmethod
    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        """Get the current status of a workflow."""
        raise NotImplementedError
    
    @abstractmethod
    async def run_appointment_saga(self, appointment_data: dict[str, Any]) -> dict[str, Any]:
        """Start an appointment booking saga workflow."""
        raise NotImplementedError


class EventPublisherAdapter(ABC):
    """Abstract interface for publishing domain events (Kafka)."""
    
    @abstractmethod
    async def publish_appointment_created(self, **metadata) -> dict[str, Any]:
        """Publish appointment created event."""
        raise NotImplementedError
    
    @abstractmethod
    async def publish_service_event(self, event_type: str, **metadata) -> dict[str, Any]:
        """Publish service-related event."""
        raise NotImplementedError


class AsyncTaskSchedulerAdapter(ABC):
    """Abstract interface for asynchronous task scheduling (Celery)."""
    
    @abstractmethod
    def schedule_follow_up(self, appointment_id: int, delay: timedelta) -> dict[str, Any]:
        """Schedule a follow-up task for an appointment."""
        raise NotImplementedError

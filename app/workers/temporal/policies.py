"""Temporal retry policies for activities and workflows.

These policies distinguish between transient errors (network, timeout) and
permanent errors (business logic violations). Compensation activities use
higher retry counts to ensure rollback succeeds.
"""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Transient errors: network timeouts, temporary unavailability
# Retry 3 times with exponential backoff: 2s → 4s → 8s (capped at 30s)
TRANSIENT_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=4,  # Initial attempt + 3 retries
    non_retryable_error_types=["AppError"],  # Don't retry business errors
)

# Business errors: validation failures, authorization, domain constraints
# No retry; fail fast and compensate
BUSINESS_ACTIVITY_RETRY = RetryPolicy(
    maximum_attempts=1,  # No retries
)

# Compensation activities: slot release, refunds, cancellations
# Retry 5 times to ensure rollback succeeds; higher backoff for system recovery
COMPENSATION_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=6,  # Initial attempt + 5 retries
)

# Workflow-level retries: for workflow start or resume failures
# Retry 3 times with longer backoff: 5s → 10s → 20s (capped at 1m)
WORKFLOW_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=4,  # Initial attempt + 3 retries
)

# Worker interruption demo: simulate transient worker failures
WORKER_INTERRUPTION_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=5),
    maximum_attempts=4,  # Initial attempt + 3 retries
)

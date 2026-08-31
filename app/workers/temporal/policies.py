from datetime import timedelta

from temporalio.common import RetryPolicy


WORKFLOW_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=3,
)

TRANSIENT_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    non_retryable_error_types=["AppError"],
)

BUSINESS_ACTIVITY_RETRY = RetryPolicy(
    maximum_attempts=1,
    non_retryable_error_types=["AppError"],
)

COMPENSATION_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
    non_retryable_error_types=["AppError"],
)

WORKER_INTERRUPTION_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=5),
    maximum_attempts=3,
)

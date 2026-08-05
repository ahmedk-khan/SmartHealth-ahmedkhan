import asyncio

from temporalio import client, worker, runtime

from app.core.settings import settings
from app.workflows.service_publish import ServicePublishWorkflow, validate_service, structure_service, chunk_service, mark_published


def main() -> None:
    runtime.Runtime.default()
    async def run_worker() -> None:
        temporal_client = await client.Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
        async with worker.Worker(
            temporal_client,
            task_queue=settings.temporal_task_queue,
            workflows=[ServicePublishWorkflow],
            activities=[validate_service, structure_service, chunk_service, mark_published],
        ) as temporal_worker:
            await temporal_worker.run()

    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

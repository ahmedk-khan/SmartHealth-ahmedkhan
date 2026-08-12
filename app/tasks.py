from app.celery_app import celery_app


@celery_app.task(name="app.tasks.trivial_ping")
def trivial_ping(message: str = "pong") -> dict[str, str]:
    return {"message": message}

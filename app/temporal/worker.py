"""Temporal worker process entrypoint."""

from app.workers.service_publish_worker import main


if __name__ == "__main__":
    main()

"""Run the analytics consumer via `python -m app.workers.kafka`."""

from app.workers.kafka.consumer import AnalyticsConsumer

if __name__ == "__main__":
    AnalyticsConsumer().run()

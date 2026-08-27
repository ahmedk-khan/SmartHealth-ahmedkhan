from app.db import SessionLocal
from app.services.analytics_service import AnalyticsService


if __name__ == "__main__":
    db = SessionLocal()
    try:
        print(AnalyticsService(db).reconcile_metrics())
    finally:
        db.close()

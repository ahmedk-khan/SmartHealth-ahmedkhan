# Architecture Diagram

```mermaid
flowchart LR
    Client --> API[FastAPI]
    API --> DB[(PostgreSQL)]
    API --> Redis
    API --> Temporal
    Temporal --> DB
    API --> Kafka
    Kafka --> Analytics[Analytics Consumer]
    Analytics --> DB
    API --> Celery
    Celery --> Redis
```

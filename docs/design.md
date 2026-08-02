# Design Notes fro smarthhealth plateform"

## Data model

- `User`: authentication account, email, password hash, role.
- `Patient`: one-to-one with `User` for patient-only data.
- `Provider`: one-to-one with `User`, belongs to a `Department`, offers many `Service`s.
- `Department`: groups providers and services.
- `Service`: medical services provided by departments and linked to providers.
- `Slot`: discrete provider schedule units with `status`, `start_datetime`, and `end_datetime`.

## Layering

- `api/`: FastAPI routers only 
- `services/`: services for buisness .
- `models/`: SQLAlchemy ORM definitions.
- `schemas/`: Pydantic request and response models.
- `core/`: configuration, security, dependencies, exception handling.


#

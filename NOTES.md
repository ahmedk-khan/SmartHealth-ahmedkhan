# Working Notes

## 2026-09-01

- Audited the documentation set and removed obsolete documentation artifacts.
- Removed the stale documentation index that referenced files no longer in the repository.
- Removed the one-case assistant safety transcript; safety behavior is documented in `docs/ai-layer.md` and covered by tests.
- Removed a broken link to the missing Temporal layering guide from `docs/design.md`.
- Added `alembic/versions/026_add_ai_interaction_telemetry.py` for AI interaction traceability and feedback fields.
- Updated assistant safety classification so heart/chest pain is refused and escalated before retrieval or LLM calls.
- Added regression coverage for the reported heart-pain request.
- Current AI evaluation status: the retrieval evaluation dataset and harness are committed, but no reproducible score is recorded without a populated indexed corpus.

## Known follow-up work

- Run the focused pytest suite and full integration checks against the Docker environment.
- Exercise the live `/assistant/ask` SSE request after applying migrations.
- Add an explicit answer-quality feedback endpoint when the product workflow is ready.

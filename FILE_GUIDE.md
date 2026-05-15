# File Guide (What to keep / what you can delete)

This guide is written for the **Docker-only (optimized)** workflow.

## Canonical runtime (keep these)

- `Dockerfile`: optimized image build (pip + `requirements.txt`, CPU-only torch).
- `docker-compose.yml`: local run (builds image locally, runs admin/user).
- `docker-compose.prod.yml`: production run (pulls prebuilt image, runs Gunicorn).
- `requirements.txt`: runtime Python dependencies for the Docker image.
- `DEPLOY.md`: deployment instructions (EC2 + CI/CD).
- `run_admin_web.py`: Flask app for admin UI (port 7860).
- `run_user_web.py`: Flask app for user UI (port 7861).
- `rag_chatbot/`: backend core (RAG, DB, auth, workers).
- `UI/`: frontend (HTML/CSS/JS).
- `data/`: persisted volumes (SQLite DB, uploaded docs, caches). Keep in production.

## Backend structure (meaning)

- `rag_chatbot/pipeline.py`: wires LLM + ingestion + retriever + query engine.
- `rag_chatbot/database.py`: SQLite schema + CRUD for users/docs/reports/history.
- `rag_chatbot/auth.py`: login/signup/session validation.
- `rag_chatbot/core/ingestion/`: document loading + chunking + node creation.
- `rag_chatbot/core/embedding/`: sentence-transformers embedding wrapper.
- `rag_chatbot/core/vector_store/`: vector store adapter.
- `rag_chatbot/core/engine/`: retriever + chat engine assembly.
- `rag_chatbot/core/model/`: LLM adapters (Gemini + GitHub Models).
- `rag_chatbot/utils/llm_resilience.py`: retry/backoff + concurrency limit for LLM calls.
- `rag_chatbot/workers/`: scheduled jobs (news fetch + summaries).

## CI/CD (meaning)

- `.github/workflows/deploy.yml`: builds/pushes Docker image and deploys to EC2 via SSH.

## Likely safe-to-delete (manual, if you truly want Docker-only)

These are not required to run via Docker, but may be useful for development/docs. Delete only if you don’t need them.

- `pyproject.toml`, `poetry.lock`, `uv.lock`, `Makefile`: Poetry/uv-based local dev tooling (not required for Docker runs).
- `restart_servers.sh`: legacy script (uses Poetry).
- `check_db.py`: helper script; not required for runtime.
- `logging.log`: local log file (can be regenerated).
- `__pycache__/` and any `*/__pycache__/`: generated Python cache.
- `BAO_CAO_*.md`, `BAO_CAO_*.txt`: project report drafts (keep if you use them for the thesis).
- `test_docs/`: sample documents for testing (keep if you need demo/test data).

## Notes

- `rag_chatbot/ollama.py` and `setting.ollama` are kept as compatibility stubs/legacy config; removing them may require additional refactors (especially anything under `rag_chatbot/eval/`).

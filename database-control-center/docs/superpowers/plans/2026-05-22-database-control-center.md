# Database Control Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first Streamlit database management app with safe CRUD workflows, audit logging, export tools, and an Ollama-powered assistant that only produces safe query plans.

**Architecture:** Use SQLAlchemy Core with dynamic table reflection so the app can browse and modify SQLite or PostgreSQL tables without ORM models. Keep the code split into focused service modules, with `app.py` orchestrating UI state, previews, confirmations, and calls into database or AI services.

**Tech Stack:** Python 3.11+, Streamlit, SQLAlchemy 2.x, Pandas, Requests, python-dotenv, openpyxl, psycopg2-binary

---

### Task 1: Project Skeleton And Configuration

**Files:**
- Create: `database-control-center/requirements.txt`
- Create: `database-control-center/.env.example`
- Create: `database-control-center/README.md`
- Create: `database-control-center/data/.gitkeep`
- Create: `database-control-center/src/__init__.py`
- Create: `database-control-center/src/config.py`

- [ ] Define the dependency list and environment examples from the spec.
- [ ] Add configuration helpers for `DATABASE_URL`, `APP_ACTOR`, `OLLAMA_BASE_URL`, and `OLLAMA_MODEL`.
- [ ] Resolve the default SQLite path under `data/app.db`.

### Task 2: Core Database And Seed Layer

**Files:**
- Create: `database-control-center/src/db.py`
- Create: `database-control-center/src/demo_seed.py`
- Test: `database-control-center/tests/test_db.py`
- Test: `database-control-center/tests/test_crud_and_audit.py`

- [ ] Write tests for engine caching, connection testing, and demo seeding.
- [ ] Implement SQLAlchemy engine helpers, connection helpers, URL masking, and database type detection.
- [ ] Create and seed `customers`, `orders`, and `audit_log` without duplicating rows.

### Task 3: Reflection, Querying, CRUD, And Audit

**Files:**
- Create: `database-control-center/src/schema_inspector.py`
- Create: `database-control-center/src/query_builder.py`
- Create: `database-control-center/src/crud_service.py`
- Create: `database-control-center/src/audit_service.py`
- Create: `database-control-center/src/export_service.py`
- Test: `database-control-center/tests/test_query_builder.py`
- Test: `database-control-center/tests/test_crud_and_audit.py`

- [ ] Write tests for safe filters, soft-delete exclusion, insert/update logging, and import-safe behavior.
- [ ] Implement reflection-based metadata helpers and query plan construction with SQLAlchemy Core.
- [ ] Implement preview-friendly insert, update, soft-delete, and CSV import service functions that always emit audit entries.

### Task 4: Ollama And AI Safety Layer

**Files:**
- Create: `database-control-center/src/ollama_client.py`
- Create: `database-control-center/src/ai_service.py`
- Test: `database-control-center/tests/test_ai_service.py`

- [ ] Write tests for strict JSON query-plan validation.
- [ ] Implement Ollama health/model/chat helpers against the local API.
- [ ] Implement prompt builders and JSON plan validation so AI never executes SQL or receives credentials.

### Task 5: Streamlit Application

**Files:**
- Create: `database-control-center/app.py`

- [ ] Build sidebar navigation and shared session state for filtered data and selected Ollama model.
- [ ] Add Dashboard, Data Explorer, Add Record, Edit Record, Import / Export, AI Assistant, Audit Log, and Settings / Health Check pages.
- [ ] Enforce preview -> confirm -> execute for every write path and surface clear success or error messages.

### Task 6: Verification And Docs

**Files:**
- Verify: `database-control-center/tests/*.py`
- Verify: `database-control-center/app.py`
- Verify: `database-control-center/README.md`

- [ ] Run the unit tests.
- [ ] Run the demo seed module.
- [ ] Validate that the Streamlit app imports cleanly.
- [ ] Document Windows and macOS/Linux startup commands, Ollama setup, PostgreSQL configuration, and safety notes.

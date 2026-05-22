# Database Control Center

Database Control Center is a local-first PySide6 desktop application for safe database investigation, browsing, controlled editing, export, audit review, and AI-assisted analysis.

The current product direction is:

`AI-Assisted Database Investigation & Control Center`

The app is designed for internal users who want a friendly desktop UI instead of a raw database client. It supports multiple database connections, keeps AI on every page through a right-side operator panel, and enforces a human approval step before any database change.

## Main Command

```powershell
python app.py
```

## Key Features

- Desktop UI built with `PySide6`
- Modern light theme with a clean, card-based layout
- Multiple database connections in one runtime session
- Right-side AI chat panel available on every page
- Data Explorer for safe search, filter, sort, and export
- Add Record, Edit Record, Import / Export, Audit Log, and Settings pages
- Default local SQLite demo database for quick startup
- PostgreSQL, SQL Server, and MySQL / MariaDB support through SQLAlchemy-compatible URLs
- Ollama integration using `llama3.2`
- Local activity logging for AI and write approval events

## Safety Model

The app starts in `READ ONLY` mode.

That means:

- browsing is allowed
- schema inspection is allowed
- export is allowed
- AI explanation is allowed
- AI filter/search suggestions are allowed
- writes are never executed silently

AI can:

- explain schema
- explain selected rows
- summarize filtered data
- draft reports
- suggest filter plans
- propose write actions

AI cannot:

- execute SQL
- open a raw SQL console
- directly change the database
- bypass the approval dialog
- receive database credentials

Every database change requires this flow:

1. A manual user action or AI proposal creates a structured write plan.
2. The app validates the plan.
3. The app shows a confirmation popup with preview and risk details.
4. The user explicitly approves.
5. The app creates a short-lived confirmation token.
6. The write executes only with that token.
7. The action is logged.

## AI Chat Panel On Every Page

The right-side AI panel is available across the application.

It can use safe page context such as:

- current page
- selected table
- current filters
- selected row
- limited result sample
- audit sample
- schema summary

It does not receive:

- database URL
- username
- password
- raw connection string

The panel supports:

- `Apply Filter Plan` for validated AI filter suggestions
- `Review Proposed Change` for AI write proposals
- copyable report drafts
- clear refusals when a request is unsafe

## Supported Pages

1. Database Login / Connection Manager
2. Dashboard
3. Data Explorer
4. Add Record
5. Edit Record
6. Import / Export
7. AI Assistant
8. Audit Log
9. Settings / Health Check

## Project Structure

```text
database-control-center/
|-- app.py
|-- requirements.txt
|-- .env.example
|-- README.md
|-- src/
|   |-- __init__.py
|   |-- activity_log.py
|   |-- ai_action_router.py
|   |-- ai_chat_panel.py
|   |-- ai_operator.py
|   |-- ai_plan_validator.py
|   |-- ai_response_parser.py
|   |-- ai_service.py
|   |-- audit_service.py
|   |-- config.py
|   |-- confirmation_dialog.py
|   |-- connection_manager.py
|   |-- crud_service.py
|   |-- db.py
|   |-- demo_seed.py
|   |-- desktop_app.py
|   |-- export_service.py
|   |-- loading_ui.py
|   |-- ollama_client.py
|   |-- query_builder.py
|   |-- schema_inspector.py
|   |-- ui_styles.py
|   |-- write_guard.py
|-- data/
|   |-- .gitkeep
```

## Requirements

- Python 3.11 or newer
- Ollama installed locally if you want AI features
- Optional PostgreSQL, SQL Server, or MySQL / MariaDB server
- On Windows for SQL Server:
  - `pyodbc`
  - `ODBC Driver 18 for SQL Server`

## Setup

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m src.demo_seed
python app.py
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.demo_seed
python app.py
```

## Demo Seed Behavior

`src.demo_seed` always seeds the local SQLite demo database only.

This is intentional.

It does not follow the currently active external `DATABASE_URL`, because the demo seed is meant to bootstrap the app safely and predictably.

## Multiple Database Support

The app reads connection profiles from `DB_PROFILES_JSON` in `.env`. If the value is missing or invalid, it falls back to:

```text
Local Demo SQLite -> sqlite:///data/app.db
```

The active database exists only in runtime state. Switching databases clears page context such as filters, last results, and selected table state before refreshing the new connection.

## `.env` Configuration

Example:

```env
APP_ACTOR=local_user
DATABASE_URL=sqlite:///data/app.db
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
DB_PROFILES_JSON=[{"name":"Local Demo SQLite","type":"sqlite","url":"sqlite:///data/app.db","description":"Default local demo database"},{"name":"Local PostgreSQL Example","type":"postgresql","url":"postgresql+psycopg2://postgres:password@localhost:5432/mydatabase","description":"Example PostgreSQL connection"},{"name":"IOO Test","type":"mssql","url":"mssql+pyodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3DSERVER%5CMSSQLSERVER2017%2C1435%3BDATABASE%3Dorder_20231025%3BUID%3Dsa%3BPWD%3D%3BEncrypt%3DMandatory%3BTrustServerCertificate%3Dyes%3BConnection+Timeout%3D30%3BAPP%3Dvscode-mssql%3BApplicationIntent%3DReadWrite%3B","description":"SQL Server target from vscode-mssql profile"}]
```

Notes:

- `DATABASE_URL` remains the default startup target.
- `DB_PROFILES_JSON` should stay on one line for reliable dotenv parsing.
- Passwords are masked in the UI.
- Manual passwords entered in the app are session-only and are not written back to disk.

## Manual Connection From The UI

Open:

`Database Login / Connection Manager`

You can:

1. review the active database and masked connection display
2. connect to a predefined profile
3. test a manual connection
4. connect to SQLite, PostgreSQL, SQL Server, MySQL / MariaDB, or another SQLAlchemy URL
5. optionally add a manual profile to the current runtime session

## Data Explorer With AI

The Data Explorer page supports:

- table selection
- keyword search
- safe filters
- sort and limit
- CSV and Excel export
- AI quick actions

Examples of what the AI panel can help with:

- `Cari customer dari Makassar yang masih active`
- `Tampilkan order yang payment_status-nya pending`
- `Jelaskan record yang aku pilih`
- `Apa data yang terlihat aneh?`
- `Buat ringkasan hasil filter ini`

If AI returns a valid filter plan, the app shows `Apply Filter Plan`. The plan is validated before being applied.

## Schema Explanation With AI

The Data Explorer schema section and the AI Assistant page can be used like a lightweight schema explorer.

Example prompts:

- `Jelaskan tabel ini dalam bahasa Indonesia`
- `Kolom mana yang kemungkinan primary identifier?`
- `Tabel ini kira-kira untuk data apa?`
- `Apa risiko kalau field ini null?`

AI may make assumptions, but it should present uncertain guesses as assumptions rather than facts.

## Report Draft Helper

The AI panel can draft reports from current page context and filtered data.

Useful draft styles include:

- Indonesian technical note
- Japanese Redmine comment
- Japanese Teams notification
- English debugging summary
- before/after validation note

The app only drafts text. It does not send messages externally.

## Ollama Setup

Install Ollama and pull the default model:

```powershell
ollama pull llama3.2
ollama serve
```

Default endpoint:

```text
http://localhost:11434
```

The selected model can be changed from `Settings / Health Check`.

## Write Approval Flow

Manual writes and AI-proposed writes use the same guarded path.

Examples:

- insert
- update
- soft delete
- CSV import
- audit_log table creation

Flow:

1. preview the change
2. open the confirmation popup
3. review database, table, action, risk, and before/after data
4. tick the approval checkbox
5. click `Approve and Execute`

If the popup is cancelled, no database change is made.

## Troubleshooting

### Ollama not running

1. Install Ollama
2. Run `ollama pull llama3.2`
3. Run `ollama serve`
4. Restart the app

### Connection failed

- Check host, port, username, password, and database name
- Confirm the server is reachable from the machine running the app
- Confirm the same connection works in another trusted client if needed

### Permission denied

- The app can open in read-only safety mode even when the database user has no write permission
- If an approved write still fails, the database account probably does not have the needed permission

### Table has no primary key

- Safe editing is limited when a table has no primary key
- Browsing and export may still work, but update flows are intentionally restricted

### AI proposed invalid action

- The app rejects unsafe or malformed AI plans
- No database change is made when validation fails

### SQL Server driver issue

- Confirm `pyodbc` is installed in the project environment
- Confirm `ODBC Driver 18 for SQL Server` is installed on Windows

### Python command issues on Windows

If `python` points to the Microsoft Store alias instead of the virtual environment, run:

```powershell
.venv\Scripts\python.exe -m src.demo_seed
.venv\Scripts\python.exe app.py
```

## Optional Windows Executable Build

If you want a packaged `.exe` later:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name "Database Control Center" app.py
```

This is optional. The application already runs directly with `python app.py`.

## Future Roadmap

- background worker threads for Ollama and long-running imports
- richer diff view for write previews
- a dedicated global search page
- stronger metadata dashboards for local activity logs
- relationship-aware navigation across related tables

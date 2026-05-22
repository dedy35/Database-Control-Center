# Database Control Center

Database Control Center is a local-first Streamlit application for browsing, searching, filtering, editing, importing, exporting, and analyzing database records without requiring end users to write SQL manually.

The app now supports multiple database connections in the same Streamlit session. Users can switch between predefined profiles from `.env` or manually connect to SQLite, PostgreSQL, SQL Server, MySQL / MariaDB, or another SQLAlchemy-compatible database URL directly from the UI. Every page uses the currently active database connection.

## Features

- Multiple database connection support with active session switching
- Predefined database profiles from `DB_PROFILES_JSON`
- Manual database login from the Connection Manager page
- Default local SQLite demo database with sample data
- PostgreSQL support via `psycopg2-binary`
- SQL Server support via `pyodbc`
- MySQL / MariaDB support via `pymysql`
- Data Explorer with safe keyword search, column filters, sorting, limits, and soft-delete exclusion
- Add Record and Edit Record pages with preview -> confirmation -> execute flow
- Bulk import with CSV preview and schema validation
- Table and filtered export to CSV and Excel
- Per-database audit logging
- Ollama assistant for schema explanation, summaries, anomaly review, and safe JSON query plans
- Floating loading overlay plus spinners for major operations

## Project Structure

```text
database-control-center/
├── app.py
├── requirements.txt
├── .env.example
├── README.md
├── src/
│   ├── __init__.py
│   ├── ai_service.py
│   ├── audit_service.py
│   ├── config.py
│   ├── connection_manager.py
│   ├── crud_service.py
│   ├── db.py
│   ├── demo_seed.py
│   ├── export_service.py
│   ├── loading_ui.py
│   ├── ollama_client.py
│   ├── query_builder.py
│   └── schema_inspector.py
└── data/
    └── .gitkeep
```

## Requirements

- Python 3.11 or newer
- Ollama installed locally if you want AI features
- Optional PostgreSQL, SQL Server, or MySQL / MariaDB server for non-SQLite use

## Setup

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m src.demo_seed
streamlit run app.py
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.demo_seed
streamlit run app.py
```

## Multiple Database Support

The app reads connection profiles from `DB_PROFILES_JSON` in `.env`. If `DB_PROFILES_JSON` is missing or invalid, the app automatically falls back to one safe default profile:

```text
Local Demo SQLite -> sqlite:///data/app.db
```

The active database is stored only in Streamlit session state during the current runtime. Switching databases updates the entire app context, including schema discovery, tables, filters, and query results.

## `.env` Configuration

Example `.env` values:

```env
APP_ACTOR=local_user
DATABASE_URL=sqlite:///data/app.db
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
DB_PROFILES_JSON=[{"name":"Local Demo SQLite","type":"sqlite","url":"sqlite:///data/app.db","description":"Default local demo database"},{"name":"IOO Test","type":"mssql","url":"mssql+pyodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3DSERVER%5CMSSQLSERVER2017%2C1435%3BDATABASE%3Dorder_20231025%3BUID%3Dsa%3BPWD%3D%3BEncrypt%3DMandatory%3BTrustServerCertificate%3Dyes%3BConnection+Timeout%3D30%3BAPP%3Dvscode-mssql%3BApplicationIntent%3DReadWrite%3B","description":"SQL Server target from vscode-mssql profile"}]
```

For `python-dotenv`, the safest format is a single-line JSON array value for `DB_PROFILES_JSON`. The provided `.env.example` already uses that format.

Notes:

- `DATABASE_URL` still exists as the default fallback URL.
- `DB_PROFILES_JSON` drives the profile dropdown in the Connection Manager.
- The UI masks passwords before displaying connection URLs.

## SQLite Example

```env
DATABASE_URL=sqlite:///data/app.db
```

## PostgreSQL Example

```env
DATABASE_URL=postgresql+psycopg2://postgres:your_password@localhost:5432/your_database
```

## SQL Server Example

```env
DATABASE_URL=mssql+pyodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3DSERVER%5CMSSQLSERVER2017%2C1435%3BDATABASE%3Dorder_20231025%3BUID%3Dsa%3BPWD%3D%3BEncrypt%3DMandatory%3BTrustServerCertificate%3Dyes%3BConnection+Timeout%3D30%3BAPP%3Dvscode-mssql%3BApplicationIntent%3DReadWrite%3B
```

## Manual Connection From The UI

Open the sidebar page:

`Database Login / Connection Manager`

From there you can:

1. Review the current active database and its masked URL
2. Select a predefined profile and connect
3. Manually enter a SQLite, PostgreSQL, SQL Server, MySQL / MariaDB, or full SQLAlchemy URL
4. Test the connection before switching
5. Optionally add the manual connection to the current Streamlit session profile list

Important:

- Manual credentials are session-only
- Manual passwords are not written to disk
- The app does not update `.env` automatically

## Demo Seed

Run the seed command once after copying `.env`:

```powershell
python -m src.demo_seed
```

This creates the demo `customers`, `orders`, and `audit_log` tables for the default SQLite database. The seed is idempotent and does not duplicate demo rows.

## Running The App

After seeding the database:

```powershell
streamlit run app.py
```

The app provides these pages:

1. Database Login / Connection Manager
2. Dashboard
3. Data Explorer
4. Add Record
5. Edit Record
6. Import / Export
7. AI Assistant
8. Audit Log
9. Settings / Health Check

## Ollama Setup

Install Ollama and pull the default model:

```powershell
ollama pull llama3.2
ollama serve
```

The default local endpoint is:

```text
http://localhost:11434
```

The app uses `OLLAMA_MODEL=llama3.2` by default, but you can change the active model name from the Settings page for the current session.

## Loading UI Notes

The app uses a practical loading UX approach for Streamlit:

- `st.spinner(...)` for operation progress
- A floating fixed-position loading badge for visibility
- Loading indicators for connect, search, add, update, soft delete, import, export preparation, and AI actions

## Security And Safety Notes

- No arbitrary raw SQL console is included
- AI never executes SQL
- AI receives only database display name, table name, schema, and sample rows
- AI never receives database credentials
- Write actions require preview and confirmation
- Hard delete is not exposed by default
- Use least-privilege or read-only users for production data where possible
- Do not connect directly to sensitive production databases unless permissions, backup, and approval are clear

## Per-Database Audit Log

Audit logging is tied to the active database. If a connected database does not contain an `audit_log` table, the app shows a warning and provides a button to create it with explicit confirmation.

The app does not automatically create `audit_log` on newly connected external databases. The only automatic creation is the default demo SQLite flow during `src.demo_seed`.

## Troubleshooting

### PostgreSQL driver issue

- Confirm `psycopg2-binary` is installed
- Re-run `pip install -r requirements.txt`

### SQL Server driver issue

- Confirm `pyodbc` is installed
- Confirm `ODBC Driver 18 for SQL Server` is installed on Windows
- Re-run `pip install -r requirements.txt`

### MySQL / MariaDB driver issue

- Confirm `pymysql` is installed
- Re-run `pip install -r requirements.txt`

### Wrong password

- Re-enter the connection details from the Connection Manager page
- Confirm the username and password outside the app if needed

### Connection refused

- Confirm the database server is running
- Confirm host and port are correct
- Confirm firewalls or local network rules are not blocking the connection

### Database does not exist

- Check the database name in the connection string
- Confirm the database has already been created on the target server

### PostgreSQL connection fails

- Verify the PostgreSQL URL format
- Confirm the database allows the chosen user to connect

### Ollama is not running

1. Install Ollama
2. Run `ollama pull llama3.2`
3. Run `ollama serve`
4. Restart the Streamlit app

### Python command issues on Windows

If `python` points to the Microsoft Store alias instead of a real interpreter, activate your virtual environment first and run:

```powershell
.venv\Scripts\python.exe -m src.demo_seed
.venv\Scripts\streamlit.exe run app.py
```

## Future Roadmap

- Saved connection presets with stronger secret management
- Relationship-aware navigation
- Better anomaly detection and reporting workflows
- More SQLAlchemy-compatible database profile examples
- Optional database capability checks for read-only or restricted modes

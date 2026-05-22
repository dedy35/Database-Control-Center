# Database Control Center

Database Control Center is a local-first Python desktop application for internal database operations. It gives non-SQL users a practical UI to browse tables, search and filter records, add and edit data with explicit confirmation, export results, inspect audit logs, and use a local Ollama assistant for safe analysis.

This version uses `PySide6` for the desktop UI. The earlier Streamlit approach has been replaced, but the backend service layer is still SQLAlchemy Core based and reusable.

## Features

- Desktop UI built with `PySide6`
- Multiple database connection support in one app session
- Predefined profiles from `DB_PROFILES_JSON`
- Manual login for SQLite, PostgreSQL, SQL Server, MySQL / MariaDB, and other SQLAlchemy URLs
- Active database switching without restarting the app
- Default local SQLite demo database with sample data
- Safe filtering and browsing without requiring manual SQL
- Preview -> confirmation -> execute flow for inserts, updates, and soft deletes
- Per-database audit logging
- CSV import with preview and validation
- CSV and Excel export
- Ollama assistant with `llama3.2`
- AI prompt safety: JSON query plans only, no SQL execution, no credential exposure
- Loading dialogs for connect, search, save, import, export, and AI operations

## Project Structure

```text
database-control-center/
|-- app.py
|-- requirements.txt
|-- .env.example
|-- README.md
|-- src/
|   |-- __init__.py
|   |-- ai_service.py
|   |-- audit_service.py
|   |-- config.py
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
|-- data/
|   |-- .gitkeep
```

## Requirements

- Python 3.11 or newer
- Ollama installed locally if you want AI features
- Optional database server for PostgreSQL, SQL Server, or MySQL / MariaDB
- For SQL Server on Windows:
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

## Multiple Database Support

The app reads connection profiles from `DB_PROFILES_JSON` in `.env`. If the value is missing or invalid, the app automatically falls back to one safe default profile:

```text
Local Demo SQLite -> sqlite:///data/app.db
```

The currently active database lives only in the application runtime state. Switching databases clears the current table context, filters, cached results, and schema state before loading the new connection.

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

- `DATABASE_URL` is still the default startup target.
- `DB_PROFILES_JSON` should stay as one JSON array on one line for reliable `python-dotenv` parsing.
- The app always masks passwords before showing connection URLs in the UI.

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
DATABASE_URL=mssql+pyodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3DSERVER%5CMSSQLSERVER2017%2C1435%3BDATABASE%3Dorder_20231025%3BUID%3Dsa%3BPWD%3Dyour_password%3BEncrypt%3DMandatory%3BTrustServerCertificate%3Dyes%3BConnection+Timeout%3D30%3BAPP%3Dvscode-mssql%3BApplicationIntent%3DReadWrite%3B
```

## Manual Connection From The UI

Open the page:

`Database Login / Connection Manager`

From there you can:

1. Review the current active database and its masked URL
2. Select a predefined profile and connect
3. Enter a manual SQLite, PostgreSQL, SQL Server, MySQL / MariaDB, or full SQLAlchemy URL connection
4. Test the connection before switching
5. Add the manual profile to the current runtime session if needed

Important security behavior:

- Manual credentials are session-only
- Manual passwords are not written to disk
- The app does not modify `.env` automatically

## Demo Seed

Run the seed command once after copying `.env`:

```powershell
python -m src.demo_seed
```

That creates the demo `customers`, `orders`, and `audit_log` tables for the default SQLite database. The seed is idempotent and does not duplicate the sample rows.

## Running The Desktop App

After seeding:

```powershell
python app.py
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

## Optional Windows Executable Build

If you want a single-file Windows executable, install `pyinstaller` separately and build from the project root:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name "Database Control Center" app.py
```

That is optional. The application runs directly with `python app.py` without packaging.

## Ollama Setup

Install Ollama and pull the default model:

```powershell
ollama pull llama3.2
ollama serve
```

Default local endpoint:

```text
http://localhost:11434
```

The app starts with `OLLAMA_MODEL=llama3.2`, and you can switch the active model from `Settings / Health Check`.

## Loading UI Notes

The desktop app uses modal loading dialogs for long-running operations such as:

- Connecting to a database
- Loading schema
- Searching records
- Saving inserts or updates
- Importing CSV data
- Exporting data
- Asking local AI

The goal is not fancy animation. The goal is clear, predictable feedback while the UI is busy.

## Security And Safety Notes

- No arbitrary raw SQL console is exposed
- AI never executes SQL
- AI never receives database credentials
- AI only receives database display name, table name, schema summary, and sample rows
- AI generates JSON query plans for safe filtering only
- Write actions require preview and confirmation
- Hard delete is not exposed by default
- Use least-privilege or read-only users when connecting to production where possible
- Do not connect directly to sensitive production databases unless permissions, backup, and approval are clear

## Per-Database Audit Log

Audit logging is tied to the active database. If a connected database does not contain `audit_log`, the UI shows that clearly and provides an explicit button to create the table in that database.

The app does not automatically create `audit_log` in newly connected external databases. The only automatic creation remains the local demo SQLite seed flow.

## Troubleshooting

### PostgreSQL driver issue

- Confirm `psycopg2-binary` is installed
- Re-run `pip install -r requirements.txt`

### SQL Server driver issue

- Confirm `pyodbc` is installed
- Confirm `ODBC Driver 18 for SQL Server` is installed on Windows
- Confirm the same connection string works in SSMS or the VS Code SQL Server extension

### Wrong password

- Re-enter the connection details from `Database Login / Connection Manager`
- Confirm the username and password outside the app if needed

### Connection refused

- Confirm the database server is running
- Confirm host, instance, and port are correct
- Confirm firewall or network rules are not blocking access

### Database does not exist

- Check the database name in the connection string
- Confirm the database already exists on the target server

### Ollama not running

1. Install Ollama
2. Run `ollama pull llama3.2`
3. Run `ollama serve`
4. Restart the application

### Python command issues on Windows

If `python` points to the Microsoft Store alias instead of a real interpreter, activate the virtual environment first and run:

```powershell
.venv\Scripts\python.exe -m src.demo_seed
.venv\Scripts\python.exe app.py
```

## Future Roadmap

- Better record pickers for very large tables
- Background worker threads for AI and long-running imports
- Saved connection profiles with stronger secret management
- Relationship-aware navigation between related tables
- More database capability checks for read-only or restricted modes

# Abakra Church Tournament Quiz Platform

Arabic-first local quiz tournament platform for church competitions.

Built with:
- Python
- FastAPI
- SQLAlchemy
- SQLite (WAL mode)
- Jinja2 + JavaScript + CSS
- openpyxl

## Features Implemented

- Role-based auth with secure Argon2 password hashing
  - Roles: `مسؤول` (Administrator), `خادم` (Game Host)
  - Login throttling and temporary lock
  - Server-side authorization on pages and APIs
- Localization / i18n
  - Languages: `ar-EG` (default), `en`
  - RTL/LTR switching
  - Persistent global default language (admin-only)
- Tournament management
  - Multiple tournaments
  - Team assignment
  - Group generation and group matches
  - Group standings with tie-break rules
- Knockout bracket management
  - Bracket generation from qualifiers
  - Byes for non-power-of-two sizes
  - Winner advancement
  - Third-place slot support
  - Draw disallowed in knockout completion flow
- Team management
  - Manual create with members
  - Excel import with resilient row-level handling
- Category & question management
  - Dynamic categories
  - Initial regular categories + special `أبونا بيسأل`
  - Manual questions written to managed workbook files
  - Excel question import (all sheets, hidden sheets included)
  - Flexible header mapping (Arabic/English)
  - Duplicate detection by content hash
- Question storage architecture
  - SQLite stores metadata/reference only
  - Question text/choices/answers loaded from workbook rows on demand
  - Managed workbook copies in app storage
- Match/game workflow
  - Transactional question reservation per match session
  - Question state tracking per session
  - Five-section flow
    1. الجماعي بوقت
    2. الجماعي سرعة
    3. فردي
    4. عجلة الحظ (+ الجوكر)
    5. أبونا بيسأل
  - Scoring rules implemented exactly:
    - Original correct: 5
    - Rebound correct: 10 (opponent)
    - Failed rebound: 0
    - Individual: no rebound
    - أبونا بيسأل: first correct team gets 10
  - Score event audit trail
  - Pause/resume/complete match with persisted state
- Dashboard and reports
  - Overview cards, category availability
  - Group tables and bracket visualization
  - CSV and XLSX export endpoints
- Reliability/security
  - SQLite WAL + FK + busy timeout
  - Transactions around session question usage/scoring
  - Safe upload checks and managed file naming
  - Audit logs for sensitive actions
- Automated tests
  - 21 tests covering auth, permissions, scoring, stage flow, locking, import, standings, knockout, localization

## Project Structure

- `app/main.py`: FastAPI app entry
- `app/models.py`: SQLAlchemy models
- `app/database.py`: engine/session, WAL/FK pragmas
- `app/security.py`: auth, role guards, password hashing
- `app/i18n.py` + `app/locales/`: localization
- `app/excel_import.py`: resilient team/question import
- `app/question_store.py`: workbook-backed question loading
- `app/game.py`: match/session state machine + locking
- `app/scoring.py`: scoring constants/rules
- `app/standings.py`: group standings
- `app/brackets.py`: knockout bracket generation/advance
- `app/match_service.py`: match completion logic
- `app/web.py`: HTML routes
- `app/api.py`: JSON APIs + report exports
- `app/templates/`: Jinja templates
- `app/static/`: CSS/JS/images
- `tests/`: automated test suite

## Installation

From workspace root (`D:\CH\Abakra`):

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Run Locally (LAN Ready)

```powershell
.\.venv\Scripts\python.exe run.py
```

Server listens on:
- `http://127.0.0.1:8000`
- `http://0.0.0.0:8000` (reachable from devices on same network using host machine IP)

## First-Run Accounts

Seeded automatically on startup:

- Admin:
  - Username: `admin`
  - Password: `admin123`
- Host:
  - Username: `host`
  - Password: `host123`

Change immediately in production-like usage.

You can override seed passwords via environment variables before first run:
- `ABAKRA_ADMIN_PASSWORD`
- `ABAKRA_HOST_PASSWORD`

## Branding Assets (Referenced Images)

Place your real logos here:
- `app/static/img/host_logo.jpg` (church host logo)
- `app/static/img/game_logo.jpg` (tournament logo)

The UI will use these directly. If missing, it falls back to bundled SVG placeholders.

## Database and Managed Storage

Managed storage defaults to:
- `data_store/abakra.db`
- `data_store/workbooks/`
- `data_store/logs/`

Overrides:
- `ABAKRA_DATA_STORE`
- `ABAKRA_DB`

Question imports are copied to managed storage so runtime does not depend on original external file locations.

## Workbook Import

### Initial Source Workbooks

Available in this repository:
- `output/final/Divinity_of_Christ_300_Questions.xlsx`
- `output/final/رسالة_العبرانين1_اختر_الاجابة_الصحيحة.xlsx`
- `output/final/بنك_الأسئلة_المجامع_الكنسية.xlsx`
- `output/final/قدرات_ذهنية.xlsx`
- `output/final/معلومات_عامة.xlsx`

Admin can import from UI (`/questions`) per category.

### Expected Question Columns

Flexible Arabic/English header mapping is supported, including variants of:
- Question text
- Choice A/B/C/D
- Correct answer
- Difficulty
- Explanation

All worksheets are processed (including hidden). Invalid rows are skipped without aborting the whole workbook.

### Team Import Columns

Supported variations for:
- Team name
- Members / member columns
- Member count

Rows with invalid/duplicate teams are skipped; summary returned.

## Manual Question Storage

Manual questions are appended to managed workbook files (`data_store/workbooks/manual_cat_<id>.xlsx`) and referenced by metadata in SQLite.

When editing manual questions, a new workbook row/version is created and old metadata is deactivated.

## Reports and Export

Admin reports page: `/reports`

Exports available as CSV and XLSX:
- Teams
- Standings by tournament
- Match results by tournament
- Question usage by tournament

## Run Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Current result:
- `21 passed`

## Backup and Restore

Backup:
- `data_store/abakra.db`
- `data_store/workbooks/`

Restore:
1. Stop app.
2. Replace DB and workbook storage from backup.
3. Start app.

## Notes / Current Limitations

- The wheel animation is client-side visual with server-side result validation.
- Timer controls are host-side controls; timer ticks are client-driven while match/question state is server-persisted.
- Existing migrations are implemented via `create_all` startup schema initialization (no Alembic workflow yet).

# AlgoFlow

A local DSA workspace: keep accepted solutions, revisit problems with spaced repetition, and record how your approach changes.

## Run the faculty demo

```sh
./start.sh
```

Open **http://127.0.0.1:3000**. The app uses `data/demo.db` by default. The server serves the built React interface and FastAPI API together.

Prerequisites: Python 3.11+ and Node 20.19+ (or 22.12+). Initial setup requires internet for dependencies. Once installed and built, the core app works offline; fonts fall back to system fonts if Google Fonts is unavailable.

If port 3000 is occupied, use `PORT=3001 ./start.sh`. The script never kills other applications.

## Your data

Initial preparation backs up the original SQLite tracker using SQLite's consistent backup API, migrates a working copy to `data/personal.db`, imports the LeetCode batch, and creates an independent `data/demo.db`.

- **Original:** `../dsa_tracker_app/dsa_tracker.db` — read only, never changed.
- **Personal:** `data/personal.db` — migrated records and 274 imported solutions.
- **Demo:** `data/demo.db` — presentation and experimentation; changes do not affect personal data.
- **Snapshots:** `data/backups/` — original and pre-reset demonstration backups.

The library starts with **275 problems**: 274 accepted export records and the preserved existing tracker problem, which has no imported acceptance yet. It also preserves Sliding Window and its review history. This is not a live count of the user's approximately 290 solved problems.

To use the personal database:

```sh
ALGOFLOW_DB="$PWD/data/personal.db" ./start.sh
```

To refresh the demo, stop the server first, then:

```sh
.venv/bin/python scripts/prepare_data.py --refresh-demo
./start.sh
```

The refresh saves a backup of the current demo before replacing it with the personal database.

Preparation is repeatable. It does not reset existing demo edits unless `--refresh-demo` is passed. On another machine, pass explicit paths with `--source` and `--export`, or import JSON through the interface.

## What works

- Batch or individual JSON import from LeetCode and GFG, including nested older GFG exports.
- Search and difficulty, platform, and topic filters.
- Sanitized offline descriptions and exact C++, C, or SQL code snapshots.
- Explicit problem and theory-topic reviews, immutable solution versions, self-assessment, and complexity notes.
- Activity, streaks, collection breakdown, full backup download, additive restore.

Historical imports have an import timestamp but **no invented solve date**. Importing never completes reviews or adds historical heatmap activity. New imported problems are due tomorrow; existing schedules are preserved. `pending` refers to review progression, not whether a solution was accepted.

Reviews follow 1 day → 7 days → 30 days → 180 days → mastered. The next interval starts on the day you complete the review. Requests include the expected stage so double clicks and stale requests cannot skip stages. Only due items can be reviewed.

Accepted imports establish acceptance. Manual code versions remain unverified and do not change acceptance or revision state. The app stores code; it does not execute or judge it.

## Architecture

```text
React interface / exported submission JSON
                 ↓
FastAPI routes + Pydantic request validation
                 ↓
Normalization / version service / review rules
                 ↓
SQLite transactions (personal OR demo database)
```

`backend/main.py` defines routes. `models.py` validates requests. `services.py` owns import, snapshots, reviews, and statistics. `database.py` owns connections and repeatable migrations. `backup.py` validates and restores exports with parent-ID remapping.

- Write transactions use `BEGIN IMMEDIATE`; problem metadata, snapshots, and review changes commit atomically.
- Problem identity: platform plus canonical URL slug.
- Snapshot identity: submission ID where available; otherwise language plus exact code fingerprint within the problem.
- Deliberate manual commits may preserve identical code with different assessments.
- Backup restore merges by problem identity or topic name/category, remaps child references, and never regresses review stages. Current titles are retained. The new schema-version-2 export is the supported restore format; the original database is handled through the migration script.
- Review dates use Asia/Kolkata; timestamps are stored in UTC and displayed in Asia/Kolkata.

## API

Explore the interactive API at **http://127.0.0.1:3000/docs**.

All endpoints use `/api/v1`:

| Endpoint | Behavior |
|---|---|
| `GET /health` | Database mode, local date, readiness |
| `GET, POST /problems` | List or manually add problems |
| `GET /problems/due` | Due and overdue queue |
| `GET /problems/{id}` | Details, versions, and review history |
| `POST /problems/{id}/review` | Complete a due review with `expected_stage` |
| `GET, POST /problems/{id}/versions` | Read snapshots or save a manual commit |
| `GET /problems/{id}/versions/{version_id}` | Read one snapshot |
| `GET, POST /topics` | List or add theory topics |
| `GET /topics/due`, `GET /topics/{id}` | Theory queue and history |
| `POST /topics/{id}/review` | Complete a theory review |
| `POST /sync/submission` | Ingest one historical submission object |
| `POST /sync/upload` | Multipart JSON file; field named `file` |
| `GET /stats`, `GET /heatmap` | Progress and recorded activity |
| `GET /backup/export` | Download complete JSON backup |
| `POST /backup/restore` | Multipart additive restore; field named `file` |

The submission endpoint is ready for later integration; this release does not modify the browser extension or implement live capture.

## Verify and develop

```sh
.venv/bin/python -m pytest -q
cd frontend
npm run build
```

Tests use temporary databases, never personal records. When the original export and tracker are available, tests additionally verify all 274 exact code snapshots and preservation of existing tracker columns.

For frontend development, run the backend normally and `npm run dev` inside `frontend/`. Vite proxies `/api` to port 3000.

`requirements.lock.txt` records the Python versions used for this demo; use `pip install -r requirements.lock.txt` for an exact reproduction. `frontend/package-lock.json` supports `npm ci`.

## Later learning milestones

1. Understand requests, validation, Python functions, and errors.
2. Rebuild small database queries and review rules yourself.
3. Learn transactions, idempotency, and meaningful tests through ingestion.
4. Add persistent live extension delivery and retries.
5. Add version comparison, C++ draft import, and summary/activity APIs for the personal planning app.
6. Add cloud synchronization and advisory AI as separate milestones.

Live capture, automatic Downloads scanning, public accounts, cloud hosting, and general goals/planning are intentionally deferred.
# AlgoFlow

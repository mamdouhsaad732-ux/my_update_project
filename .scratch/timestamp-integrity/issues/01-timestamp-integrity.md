# 01 — Timestamp integrity, safe purge policy, DB testability seam

- **Status**: resolved
- **Type**: task
- **Blocks**: 02 (QR credential), 03 (report loop) — both need a working archive date and a
  database the tests can reach.

## Objective

1. `PatientRecord.created_at` gets a callable default, so each insert is stamped at insert
   time instead of at module import (`main.py:36`).
2. The 30-day auto-purge becomes opt-in via `PURGE_ENABLED` (default `false`), with logging
   on deletion (`main.py:75-98`, call site `main.py:165`).
3. The database URL is read from `DATABASE_URL`, falling back to the current SQLite path
   (`main.py:21`).

## Architecture impact

| Component | Change |
|---|---|
| SQLAlchemy model | `created_at` default becomes a callable; column type unchanged |
| Startup/import | DB URL resolved from env; engine construction otherwise unchanged |
| Admin dashboard (`GET /doctor`) | Purge call becomes conditional on the flag |
| Retention job (`cleanup_old_records`) | Adds logging; deletion logic unchanged |
| Tests | New `tests/test_timestamp.py`, first test infrastructure in the repo |

## Plan

1. Snapshot `main.py` and `requirements.txt` into `baseline/`, record `MANIFEST.sha256`.
2. Write failing tests in `tests/test_timestamp.py` (red).
3. Implement in `main.py`:
   - `_now_string()` helper returning `str(datetime.datetime.now())`;
   - `created_at = Column(String, default=_now_string)`;
   - `DATABASE_URL` env read with the current literal as fallback;
   - `PURGE_ENABLED` parsing (case-insensitive `true`/`1`/`yes`), default off;
   - `logger = logging.getLogger(__name__)`, one info line per deleted record plus a summary;
   - gate `cleanup_old_records(db)` at the `/doctor` call site.
4. Add `pydicom`, `Pillow`, `numpy` to `requirements.txt` (currently missing, so the app cannot
   import on a fresh install) and create `requirements-dev.txt` with `pytest` + `httpx`.
5. Re-run the suite (green).
6. Phase 3 review; fix findings; re-run.

## Risk assessment

**Low.** All three changes are additive or default-preserving:

- The callable default produces the same string format as today, so archive slicing,
  `strptime` parsing and the 30-day comparison keep working unchanged.
- `DATABASE_URL` unset resolves to the identical URL as today.
- `PURGE_ENABLED` unset means the purge no longer runs automatically. This is the one
  behavioural change, and it is the point of the ticket. Rollback: set
  `PURGE_ENABLED=true`, or restore `main.py` from `baseline/`.

**Isolation:** changes are confined to `main.py` lines 1-39, the `cleanup_old_records`
function, and the `/doctor` handler. No template, route signature, schema or file layout
changes.

## Deviations to report

- `requirements.txt` gains three entries the ticket did not name explicitly, because the
  acceptance criterion "full suite green" is unreachable without them (`import main` pulls
  `pydicom`, `PIL`, `numpy`).
- `tests/test_timestamp.py` sets `DATABASE_URL` before importing `main`, so no `conftest.py`
  is needed yet. If a second test module appears, extract that into `tests/conftest.py`.

## Resolution

**Resolved.** `pytest tests/` → 26 passed. Baseline re-run → 14 failed, 3 passed, so the
tests discriminate. Review record: `.scratch/timestamp-integrity/review.md`.

### What shipped

- `created_at_default()` — callable default, `strftime(TIMESTAMP_FORMAT)`, always 26 chars,
  always microsecond-precise. `parse_timestamp()` inverts it and tolerates legacy rows
  written without microseconds.
- `DATABASE_URL` honoured at import; `DEFAULT_DATABASE_URL` keeps `sqlite:///./medical_pacs.db`.
  `CONNECT_ARGS` is scheme-branched so a non-SQLite URL does not explode at import.
- `purge_enabled()` — `PURGE_ENABLED` read **at call time**, truthy set `{1,true,yes}`.
  `/doctor` calls `cleanup_old_records` only when it returns true.
- `cleanup_old_records` returns a count, logs one line per purged record **after** a successful
  commit, logs the sweep summary, rolls back and logs a failure instead of swallowing it.
- `_configure_logging()` installs a root handler only when the host app configured none.
- `tests/conftest.py` — throwaway DB configured before any import, plus a fail-fast guard that
  raises instead of letting `clean_db` drop tables in the live database.
- `requirements.txt` — `pydicom`, `Pillow`, `numpy` added (the app could not import without them).

### Deviations from the ticket text

1. **Fallback is `medical_pacs.db`, not `medical.db`.** The continuation prompt named
   `sqlite:///./medical.db`; that would silently point the app at a different, empty database
   and make every existing patient record disappear from the UI. The historical default was
   kept and is pinned by `test_database_url_falls_back_to_default`.
2. **Two log lines beyond "one per deletion + summary"** — an accurate warning for records that
   cannot be parsed or whose files cannot be removed, and `logger.exception` for a failed sweep.
   Both replace silent `pass` blocks. Declared in `review.md`.
3. **`tests/conftest.py` added** — the ticket listed only `tests/test_timestamp.py`. The env
   setup cannot live in the test module: a second module importing `main` first would bypass it
   and `clean_db` would then drop the real tables.
4. **`requirements-dev.txt`** created as the ticket listed; it pins nothing yet, matching the
   unpinned style of `requirements.txt`.

### Deferred

- `remove_record_files(record)` extraction — three near-identical delete blocks
  (`cleanup_old_records`, `doctor_delete_record`, `technician_delete_record`). Out of this
  ticket's line scope; belongs with Ticket 03.
- `created_at` is still `Column(String)`. A `DateTime` column needs a real migration path.

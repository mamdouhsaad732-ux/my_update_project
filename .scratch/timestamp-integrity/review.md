# Ticket 01 — review record

Two-axis review of `.scratch/timestamp-integrity/changes.diff` (baseline vs working tree).
Both axes ran as parallel fresh-context sub-agents; the Spec axis independently re-ran the
suite against `baseline/main.py` (14 failed, 3 passed) before reviewing.

Baseline integrity at review time: `main.py` and `requirements.txt` both match
`baseline/MANIFEST.sha256`. Snapshot untouched, so the diff is trustworthy as the record of
what changed.

---

## Standards

**Documented standards:** none. No `CODING_STANDARDS.md`, no `CONTRIBUTING.md`; `AGENTS.md`
records issue-tracker and domain-doc conventions only. So the only standard is the smell
baseline.

**Smells found (all judgement calls):**

| Smell | Location | Disposition |
|---|---|---|
| Mysterious Name — `PURGE_ENABLED_VALUES` held only truthy spellings | `main.py:30` | Fixed → `PURGE_TRUTHY_VALUES` |
| Mysterious Name — `_now_string` named the type, not the role | `main.py:33` | Fixed → `created_at_default` |
| Duplicated Code / Primitive Obsession — format re-derived in 3 places | `main.py:40`, `:104`, tests | Fixed → `TIMESTAMP_FORMAT` + `parse_timestamp()` |
| Duplicated Code — `split(",")/lstrip("/")` + `"temp.png"` rule now in its 3rd/4th copy | `main.py:107-116` | Deferred — extraction touches three delete routes outside this ticket's line scope (Ticket 03) |
| Duplicated literal — default DB URL restated in tests | tests | Rejected — an independent expectation beats DRY; comparing the constant to itself is a tautology |

**Correctness findings:**

| Finding | Disposition |
|---|---|
| `if deleted:` ran outside `try`, so a failed commit still logged deletions | **Fixed** — collect ids, commit, then log |
| `connect_args={"check_same_thread": False}` is SQLite-only; the new seam admits `postgresql://` | **Fixed** — scheme-branched `CONNECT_ARGS` |
| `str(datetime.now())` drops `.000000` when µs == 0, so `%f` parsing is not guaranteed | **Fixed** — `strftime(TIMESTAMP_FORMAT)` |
| Test env set at import; another module importing `main` first would `drop_all` the real DB | **Fixed** — moved to `conftest.py` + fail-fast guard on the engine path |
| `getattr(r, "record_id", None)` is never set, so the log assertion was a loose substring match | **Fixed** — exact `id=<n> ` prefix, count == 1 |
| `requirements.txt` diff "does not apply" | **Not a defect** — baseline had no trailing newline (last bytes `111,117,115`); verified by byte inspection |

---

## Spec

**Missing / partial:**

1. Spec:67 — "unset **or false**" — only *unset* was exercised end-to-end. → **Fixed**: `test_explicit_false_values_do_not_purge` covers `false`/`0`/`no`/`off` through `/doctor`.
2. Spec:69 — "upload paths unchanged" had no test. → **Fixed**: `test_upload_creates_record_with_fresh_timestamp` posts a real multipart PNG through `/technician/upload`.
3. Spec:23 — the fallback test ran `import main` in the repo root, so `create_all` touched `./medical_pacs.db`. → **Fixed**: subprocess now runs in a scratch cwd with `static/` and `PYTHONPATH`.

**Not asked for (scope creep):**

1. `"on"` invented as a truthy value, untested. → **Fixed**: `PURGE_TRUTHY_VALUES = {"1","true","yes"}`, and `"on"` moved into the falsey test.
2. `logger.warning` + `logger.exception` beyond "one line per deletion plus a summary". → **Partly kept, declared**: the misleading "unparseable" label is gone (parse failures and filesystem failures now log separately and accurately), and the sweep-failure `logger.exception` stays. Rationale: the original code swallowed both with `pass`; a "safe purge" that cannot report a failed sweep reproduces the bug this ticket exists to fix.

**Implemented but wrong:**

1. **Deletion log invisible in deployment** — `logging.getLogger(__name__)` with no handler; uvicorn leaves root at `[]` handlers/`WARNING`, so INFO was dropped outside pytest. → **Fixed**: `_configure_logging()` installs a root handler only when none exists; `test_retention_log_is_visible_without_host_logging_config` asserts `isEnabledFor(INFO)` and that the record reaches a handler in a bare interpreter.
2. **Log assertion coincidence-satisfiable** — deleting the per-record line left the test green (`old_id` is always 1, and the summary line matched). → **Fixed and proven by mutation**: removing `logger.info("retention: purged record id=…")` now fails the test; restoring it passes.
3. **Log before commit** — deletions logged before `db.commit()`. → **Fixed**: post-commit logging; rollback returns `0` and logs a failure instead.
4. **Format not guaranteed** — same root cause as the Standards axis. → **Fixed**.
5. **Non-discriminating tests** — `test_timestamps_are_groupable_by_day` and `test_purge_enabled_keeps_recent_records` passed against baseline unchanged. → **Strengthened**: grouping test now inserts two records two days apart and asserts distinct `[:10]` buckets.

Purge call sites checked: `main.py:196-197` is the only invocation; nothing bypasses the gate.
`DATABASE_URL` is read at import (per criterion); `PURGE_ENABLED` at call time (testable without reloading).

---

## Summary

- **Standards:** 12 findings — 9 fixed, 1 deferred (file-removal extraction), 1 rejected with reason (test literal), 1 disproved (diff artifact). Worst: deletions logged before a commit that could roll back.
- **Spec:** 10 findings — 9 fixed, 1 kept as a declared deviation (extra failure logging). Worst: the deletion log was invisible in deployment while the test suite stayed green.

## Phase 4 verification

| Check | Result |
|---|---|
| Red (baseline) | 14 failed, 3 passed |
| Green (working) | 26 passed |
| Mutation: remove per-record log | 1 failed — assertion is now discriminating |
| Mutation: restore | 26 passed |
| Baseline snapshot integrity | both files match `MANIFEST.sha256` |
| App imports | 26 routes registered, no import error |

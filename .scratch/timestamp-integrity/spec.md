# Spec: Timestamp integrity, safe purge policy, DB testability seam

## Problem

`PatientRecord.created_at` uses `default=str(datetime.datetime.now())` (`main.py:36`). The
right-hand side is evaluated **once at module import**, so every row inserted by a running
process receives the identical timestamp — the moment the server booted.

Three consequences:

1. **Archive grouping collapses.** Month/day pages slice `created_at[:7]` / `[:10]`
   (`main.py:239, 277-278, 316`), so every record created by this process lands in one bucket
   regardless of when it was actually created.
2. **Latent data loss.** `cleanup_old_records` deletes records older than 30 days and runs on
   every `/doctor` page load (`main.py:75-98, 165`). For a process that has been up longer than
   30 days, a *freshly uploaded* record is stamped with a boot time that is already past the
   cutoff, and is destroyed on the next admin page view.
3. **The purge is silent and unrequested.** It deletes patient records and their files with no
   log line, no confirmation, and no way to turn it off.

Separately, the database URL is a module-level literal (`main.py:21`) and the engine is built,
plus `Base.metadata.create_all()` executed, at import (`main.py:39`). Tests cannot point the
app at a throwaway database without writing to the real one.

## Scope

- `created_at` default becomes a callable, so each insert is stamped at insert time.
- The auto-purge becomes opt-in via `PURGE_ENABLED`, default off, and logs what it deletes.
- The database URL is read from `DATABASE_URL`, falling back to the current SQLite path.

## Out of scope

- The `String` column type itself (a `DateTime` migration is a schema change, not this ticket).
- Timezone handling / UTC normalisation (see Decision 1).
- The hardcoded session secret, plaintext passwords, and unauthenticated routes (Ticket 02/04).
- The broken `/save-report` route (Ticket 03).

## Decisions

**Decision 1 — `datetime.datetime.now()`, not `utcnow`.** The ticket allowed "utcnow or
equivalent". The stored value must stay a **string in the existing `%Y-%m-%d %H:%M:%S.%f`
format**, because `cleanup_old_records` (`main.py:82`) parses it with `strptime` and the
archive pages slice it as a string. Moving to UTC while every consumer still compares against
naive local `datetime.now()` would shift the 30-day cutoff by the local UTC offset, and would
move day boundaries for records created near midnight. Local naive time keeps every existing
consumer correct. Timezone normalisation is a correct-but-larger change; it is deliberately
not bundled into a data-loss fix.

**Decision 2 — `_now_string()` returns `str(datetime.datetime.now())`.** The column is
`Column(String)`, and the SQLite DBAPI has no adapter for `datetime` objects; returning a
`datetime` from the default would raise on insert. The callable must produce the same string
format the rest of the module already parses.

**Decision 3 — purge stays implemented, not deleted.** `PURGE_ENABLED` gates the call site,
so the retention feature remains available and testable. The purge itself is otherwise
unchanged, except for a log line per deletion and a summary count.

**Decision 4 — test seam is env-var only.** `DATABASE_URL` with the existing value as
fallback. No app factory, no dependency-injection rework: those are Ticket 04+ material.

## Acceptance criteria

- [ ] Inserting two records in the same process yields two different `created_at` values, each
      parseable by `strptime` with `%Y-%m-%d %H:%M:%S.%f`, and each within seconds of now.
- [ ] `DATABASE_URL` set before import is honoured by `engine`; unset falls back to
      `sqlite:///./medical_pacs.db`.
- [ ] With `PURGE_ENABLED` unset or false, a 40-day-old record survives a `/doctor` request.
- [ ] With `PURGE_ENABLED=true`, the same record is deleted and the deletion is logged.
- [ ] Existing behaviour otherwise unchanged: record creation, dashboard render, upload paths.
- [ ] Full suite green; no pre-existing test regressions (there are none today).

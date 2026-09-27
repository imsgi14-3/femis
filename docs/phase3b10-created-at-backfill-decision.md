# Phase 3B.10 - `created_at` Backfill Decision (student id 8)

Produced **before** any value was written, as required by the 3B.10 STOP-first rule.

## 1. Student ID

**8 - "Ahmed Khan"** (`b_form=35202-1234567-1`), the designated test student.

## 2. Current NULL state

`students.created_at IS NULL` for exactly one row in the database: **id 8**. Confirmed by
the pre-migration inspection (`docs/phase3b10-pre-migration-state.json`:
`null_created_at_ids: [8]`, DB SHA-256 `71064b82...946`). The same row was already NULL in
the 3B.3 pre-migration snapshot (`docs/phase3b3-pre-migration-state.json`, recorded
2026-09-24, `students_created_at_null_count: 1`).

## 3. Evidence examined

1. **Git history of `insert_test_record.py`** - the script (raw `DELETE` + `INSERT`, no
   `created_at`) is the documented producer (`docs/db-canonical.md:45`). History:
   added `43fbce7` 2026-09-22 02:19:04 UTC; modified `5c98f76` 2026-09-22 10:50 UTC;
   modified `87c7964` 2026-09-24 05:12 UTC. **Commit times are edit times, not run times** -
   and because the script deletes and re-inserts the row on every run, the current row's
   age equals the *last run*, which is nowhere recorded.
2. **Rowid bounding (strongest constraint, but only a window)** - the row has `id=8`, which
   SQLite assigns as `max(rowid)+1`; for the insert to have received id 8, no row with
   `id >= 8` could exist at that moment. Student 9 was inserted at `2026-09-23 10:07:11`
   (its ORM `created_at`, trusted per the 3B.9 audit) and student 6 at
   `2026-09-22 05:20:45`; an id-7 row existed first. Therefore the current id-8 row was
   created inside the window **(2026-09-22 05:20:45, 2026-09-23 10:07:11) UTC** - a ~29-hour
   span.
3. **3B.3 pre-migration state (2026-09-24)** - NULL already present, so the last script run
   happened before 2026-09-24 (consistent with window above).
4. **Ahmed's `updated_at` = 2026-09-26 15:04:35** - set by later activity (3B.6-era
   `save-tab` updates and the startup `COALESCE(created_at, CURRENT_TIMESTAMP)` migration of
   `updated_at`), not by row creation.
5. **Database file mtime (2026-09-26)** - supporting evidence only, as the brief requires:
   any write to the file updates it; it does not date this row.
6. **3B.6 evidence** (`p3b6_*`, job created 2026-09-26 13:21 UTC) - post-dates creation;
   documents use of the row, not its birth.
7. **`data/logs` audit screenshots (2026-09-20/21)** - portal-side captures; not DB row
   creation events.

## 4. Evidence supporting the chosen value

The chosen value is the moment this remediation decision was finalized (below). It is
supportable because it is **exactly when the write will occur**, is fully reproducible from
this document, and makes no claim about the past. Every candidate historical source in
section 3 is either a non-event-time (commits, mtimes) or a range (rowid window).

## 5. Historical or migration-assigned?

**Migration-assigned (`source = migration_backfill`).** Not Ahmed's true historical creation
time. The historical creation time is unrecoverable: the producing script overwrote the row
on each run and recorded nothing.

## 6. Exact value to be written

```text
2026-09-26 16:59:22
```

(naive UTC, matching the `datetime.utcnow` convention of every other `students.created_at`
row; written verbatim to `students.created_at WHERE id = 8`, no other column touched.)

## 7. Why no alternative was selected

- **Git commit timestamps** - commit time != script run time; selecting one would invent
  precision the repository cannot support.
- **Rowid window midpoint or boundary** - a ~29h window cannot defensibly yield an instant;
  any point inside it is arbitrary and would *pretend* to be historical.
- **`updated_at` / file mtime / 3B.6 evidence times** - all demonstrably post-creation.
- **"Now" as an unmarked value** - rejected precisely because it would misrepresent a
  migration write as a creation event; hence the explicit `migration_backfill` provenance
  recorded here (the schema itself carries no provenance column, so this document is the
  authoritative record).

**Ambiguity check:** the evidence bounds but cannot pinpoint the historical instant - this
is a *known-and-documented* limitation with a sanctioned fallback (Class B), not a safety
ambiguity. Per the phase brief, execution continues.

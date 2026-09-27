# FEMIS Canonical Database Decision

**Date:** 2026-09-24 (Phase 1 of the separation plan — see `docs/femis-separation-audit.md`)
**Status:** Decision recorded. No schema changes, no application behavior changes.

## 1. Canonical database

**`femis-web/instance/femis.db`** is the single canonical contract database shared by the Student Portal and the FEMIS Bot.

Absolute path: `C:\Users\faiza\OneDrive\Documents\IMSG I-14\FemisBot\femis-web\instance\femis.db`

Note: the Flask app honors a `DATABASE_URL` environment variable if set (`femis-web/app.py:17-20`); the canonical claim applies to the default path (no `DATABASE_URL` override), which is what local development and the bot use.

## 2. Why it is canonical — code references

Every code path that touches a database points at `femis-web/instance/` (or fallbacks inside `femis-web/`). **Zero code references the repo-root `instance/femis.db`** (only historical notes in `docs/` and `SESSION_HANDOFF.md` mention it).

| Consumer | Reference | Path used |
|---|---|---|
| Student Portal (Flask/SQLAlchemy) | `femis-web/app.py:14-20` — `SQLALCHEMY_DATABASE_URI` defaults to `os.path.join(_basedir, "instance", "femis.db")` where `_basedir` = `femis-web/` | `femis-web/instance/femis.db` |
| FEMIS Bot (DB-driven runs) | `src/data_sources/webform_handler.py:8` — `DB_PATH = ... / "femis-web" / "instance" / "femis.db"` | `femis-web/instance/femis.db` |
| Bot fallback | `src/data_sources/webform_handler.py:11` — `DB_PATH_LOCAL = ... / "femis-web" / "femis.db"` | `femis-web/femis.db` (absent) |
| Bot search fallbacks | `src/data_sources/webform_handler.py:26-30` — `femis-web/femis.db`, `femis-web/instance/femis.db`, `../femis-web/...` | never root `instance/` |
| Test-data helper | `insert_test_record.py:5` | `femis-web/instance/femis.db` |
| WSGI / deploy | `femis-web/wsgi.py`, `Procfile`, `render.yaml` — run the Flask app under `femis-web/` | `femis-web/instance/femis.db` |

The repo-root `instance/femis.db` is an orphan artifact from before commit `539f86d` ("Fix SQLite DB path to absolute"); nothing opens it anymore.

## 3. Database paths

| Role | Path | Status |
|---|---|---|
| Canonical | `femis-web/instance/femis.db` | LIVE — Flask + bot |
| Archived (was stale root copy) | `backup/2026-09-24/archived-root-instance/femis.db` | Moved out of `instance/` on 2026-09-24; **not deleted** |
| (former location of stale copy) | `instance/femis.db` | File moved; `instance/` directory left empty |

## 4. Record counts (as of backup, 2026-09-24)

| Database | `students` rows | `students.id` values | `teachers` table | `teachers` rows |
|---|---|---|---|---|
| `femis-web/instance/femis.db` (canonical) | 6 | 3, 4, 6, 7, 8, 9 | present | 1 |
| root `instance/femis.db` (stale, archived) | 7 | 1, 2, 3, 4, 5, 6, 7 | **absent** | 0 |

Canonical data notes:
- `students.id=8` ("Ahmed Khan") has `NULL` `created_at` / `submitted` — inserted via raw SQL in `insert_test_record.py` (bypasses SQLAlchemy defaults).
- `students.id=7` is the self-cleaning smoke-test row ("E2E Smoke Student", recreated by `browser_smoke_test.py`).

## 5. Schema differences

Full dump: `docs/phase1-schema-dump.json` (columns, types, nullability, DDL, row counts for both DBs and both SQLAlchemy models).

### 5.1 `students` — column counts

| Source | Columns |
|---|---|
| Canonical DB | **140** |
| Stale root DB | **134** |
| SQLAlchemy `Student` model (`femis-web/app.py:49`) | **139** |

### 5.2 Column-set differences

**Canonical DB vs stale root DB**
- Only in canonical (6): `address`, `disability_certificate`, `guardian_email`, `present_sub_sector_id`, `sub_sector_id`, `transport`
- Only in stale: *(none — stale is a strict subset of the canonical column set)*

**Canonical DB vs SQLAlchemy `Student` model**
- In DB but not in model (1): `transport` — legacy column from an older model revision; kept by SQLite (never dropped); harmless but orphaned.
- In model but not in DB: *(none — model fully covered; the two columns added by the ad-hoc migration at `app.py:36-40`, `sub_sector_id` / `present_sub_sector_id`, are present)*
- Type / nullability mismatches between canonical DB and model: **none**.

**Stale root DB vs SQLAlchemy `Student` model**
- Model columns missing from stale DB (5): `address`, `disability_certificate`, `guardian_email`, `present_sub_sector_id`, `sub_sector_id`
- Extra columns in stale DB: *(none)*
- Stale DB also lacks the entire `teachers` table.

### 5.3 `teachers` — canonical DB vs model

Identical: `id`, `name`, `password_hash`, `class_id`, `section_id`, `created_at` (6 columns, exact match).

### 5.4 Row-level divergence (why the two DBs cannot be merged)

- Overlapping ids hold **different data**:
  - `id=3`: canonical "Ali Khan" vs stale "A"
  - `id=4`: canonical "Test2" vs stale "Ali"
  - `id=6`: canonical "Ayat Mubeen" vs stale "Test"
  - `id=7`: "E2E Smoke Student" in both (same name, different `created_at`)
- Stale `id=5` ("Ayat Mubeen", `created_at=2026-09-22 05:20:45.030902`) matches canonical `id=6` name+timestamp — the same logical row received a different autoincrement id after the DB-path fix. Ids are not a stable join key across the two files.
- Stale-only ids: `1` ("asdf"), `2` ("Asdf"), `5` ("Ayat Mubeen"). Canonical-only ids: `8`, `9`.

Conclusion: no safe automated merge; canonical file stands alone; stale file is archived for manual review only.

## 6. Backups

Created 2026-09-24 using the SQLite online backup API (consistent snapshot even with the Flask dev server running):

| File | Source | SHA-256 |
|---|---|---|
| `backup/2026-09-24/canonical_candidate.femis.db` | `femis-web/instance/femis.db` | `A7618D570B4E5B1FEFCEA3A90AC9D051D81184AED836D5BEFA2D9D2071B97DBC` |
| `backup/2026-09-24/root_stale.femis.db` | root `instance/femis.db` (pre-move copy) | `880EA8DACF89FC894506947CA251DACB9A13151F4AC817F0E5CAF2B0DCA1B4C0` |
| `backup/2026-09-24/archived-root-instance/femis.db` | root `instance/femis.db` (moved file, byte-identical to `root_stale.femis.db`) | `880EA8DACF89FC894506947CA251DACB9A13151F4AC817F0E5CAF2B0DCA1B4C0` |

`backup/` and `*.db` are covered by `.gitignore` (`*.db`, `instance/`, `femis-web/instance/`) — backups are local files only, not committed.

## 7. Stale root DB decision

- **Archived, not deleted.** The file was moved to `backup/2026-09-24/archived-root-instance/femis.db` (plus an identical byte-copy backup at `backup/2026-09-24/root_stale.femis.db`).
- **Rationale:** no code reads it, but it contains three ids (`1`, `2`, `5`) never written to the canonical DB, and its overlapping ids diverge — so it must not be merged and must not be destroyed until those unique rows are manually reviewed.
- **Do not recreate** `instance/femis.db`. If any tool recreates a file there, treat it as a bug (nothing should open that path).
- Eventual deletion of the archived copy requires an explicit human decision after reviewing ids `1`, `2`, `5`.

## 8. Out of scope (per Phase 1 rules)

Not done in this phase: `bot_jobs` table, job API endpoints, bot claim loop, any 7-tab form changes, and the known data-integrity fixes (Tab 7 persistence, `transport_facility`, `refugee_card_number`, `disability_types`, bot false-success reporting). Those are Phase 2+ per the approved plan.

# FEMIS Deployment & Sync Runbook

Covers the PythonAnywhere deployment (primary), schema-change discipline
(record retention), and the one-way SQLite sync to the local bot machine.

---

## 1. One-time PythonAnywhere setup

1. **Bash console:** clone the (public) repo:
   ```bash
   cd ~ && git clone https://github.com/imsgi14-3/femis.git femis
   ```
2. **Virtualenv** (deps: flask, flask-sqlalchemy, gunicorn, python-dotenv):
   ```bash
   cd ~/femis && python3.11 -m venv venv
   venv/bin/pip install -r femis-web/requirements.txt
   ```
3. **Web tab:**
   - Directory: `/home/<user>/femis`
   - Virtualenv: `/home/<user>/femis/venv`
   - WSGI configuration file:
     ```python
     import sys
     sys.path.insert(0, '/home/<user>/femis/femis-web')
     from wsgi import app as application
     ```
   - **Environment variables** (never in the repo — it is public):
     | Key | Purpose |
     |---|---|
     | `SECRET_KEY` | Flask sessions (random long string) |
     | `FEMIS_ADMIN_NAME` / `FEMIS_ADMIN_PASSWORD` | first-boot admin seed |
     | `FEMIS_OPERATOR_TOKEN` / `FEMIS_BOT_TOKEN` | job-API gates (optional until bot API used) |
4. **First load** bootstraps everything automatically — no manual DB step:
   - `femis-web/instance/femis.db` is created by `db.create_all()` + the
     idempotent startup migration block (`app.py`, "Schema bootstrap").
   - The admin account is seeded from `FEMIS_ADMIN_*` when no admin exists.
   - The login page hides the "Setup Admin" box once an admin exists.

## 2. Updating the deployed code (every push)

```bash
cd ~/femis && git pull origin main
```
Then **Web tab → Reload**, then hard-refresh the browser (Ctrl+F5).
Python code is frozen in the worker until Reload; HTML/JS/templates are
served from disk (`TEMPLATES_AUTO_RELOAD=True`).

**Backup before pulling** when a schema change is included (see §3):
```bash
cd ~/femis/femis-web/instance && cp femis.db femis.db.bak-$(date +%F-%H%M)
```

## 3. Schema-change discipline (retain records)

The startup-migration block in `femis-web/app.py` runs on **every boot of
every environment** (PA + local) right after `db.create_all()`. Its rules:

- **Additive only.** New tables come from `db.create_all()`; new columns from
  `PRAGMA table_info`-guarded `ALTER TABLE … ADD COLUMN`; indexes from
  `CREATE INDEX IF NOT EXISTS`; backfills from idempotent
  `UPDATE … WHERE col IS NULL`.
- **Never DROP or rename in place.** A rename = add the new column, backfill
  from the old one, keep the old column until both sides have migrated
  (drop it in a later, separate release).
- **Same code both sides ⇒ same schema.** After `git pull` + reload on PA
  and restarting local processes, the two schemas are identical by
  construction.
- **Backup first** (PA: `cp` command above; local: the sync script does it).
- Only if a change cannot be expressed additively, introduce
  Flask-Migrate/Alembic — not before.

## 4. SQLite sync: portal → local bot machine

PA is the data-entry primary (teachers/parents enter records there). The bot
machine pulls a consistent snapshot:

```bash
# local dev server must be stopped (Windows cannot swap an open file)
python tools/sync_from_portal.py
```

What it does:
1. Backs up `femis-web/instance/femis.db` → `data/backups/femis.db.bak-<ts>`
2. Logs into the portal as admin (`FEMIS_PORTAL_URL`, `FEMIS_ADMIN_*`)
3. Downloads `GET /api/admin/export` (sqlite3 backup API snapshot,
   admin-session gated) and validates header + `PRAGMA integrity_check`
4. Atomically replaces the local DB (clear error if the server is still up)

It is **wholesale replacement, never a merge** — run it whenever the bot
needs fresh records. Env vars live in the repo-root `.env` (gitignored);
`.env.example` documents the keys.

## 5. Roles at a glance

| Capability | Student | Teacher | Admin |
|---|---|---|---|
| Own record (class+section match for teachers) | own only | own class/section | all |
| Create teachers / reset password / delete teacher | — | — | yes |
| Delete students | — | own class/section | all |
| DB export (`/api/admin/export`) | — | — | yes |
| Job API (human operator, with token) | — | yes | yes |
| Locked record editing | blocked | yes | yes |

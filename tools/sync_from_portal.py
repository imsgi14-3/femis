"""One-way portal -> local SQLite sync (PythonAnywhere is the primary).

Usage — repo root, local dev server STOPPED:
    python tools/sync_from_portal.py

Steps:
  1. Backup local femis-web/instance/femis.db -> data/backups/femis.db.bak-<ts>
  2. Login to the portal as admin (FEMIS_PORTAL_URL / FEMIS_ADMIN_NAME /
     FEMIS_ADMIN_PASSWORD from .env or the environment)
  3. GET /api/admin/export -> verify SQLite header + PRAGMA integrity_check
  4. Atomically replace the local DB

This REPLACES the local DB wholesale (no merge). The bot is read-mostly;
run the script whenever you need fresh records on the bot machine.
"""
import datetime
import os
import shutil
import sqlite3
import sys
from http.cookiejar import CookieJar
from pathlib import Path
from urllib import error, parse, request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "femis-web" / "instance" / "femis.db"
BACKUPS = ROOT / "data" / "backups"


def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def main():
    url = (os.environ.get("FEMIS_PORTAL_URL") or "").strip().rstrip("/")
    name = (os.environ.get("FEMIS_ADMIN_NAME") or "").strip()
    password = (os.environ.get("FEMIS_ADMIN_PASSWORD") or "").strip()
    if not url:
        fail("FEMIS_PORTAL_URL not set (e.g. https://<user>.pythonanywhere.com)")
    if not (name and password):
        fail("FEMIS_ADMIN_NAME / FEMIS_ADMIN_PASSWORD not set")
    if not DB.exists():
        fail(f"local DB not found: {DB}")

    # --- 1. backup -------------------------------------------------------
    BACKUPS.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup = BACKUPS / f"femis.db.bak-{ts}"
    shutil.copy2(DB, backup)
    print(f"local backup -> {backup}")

    # --- 2. portal login -------------------------------------------------
    jar = CookieJar()
    opener = request.build_opener(request.HTTPCookieProcessor(jar))
    body = parse.urlencode({"role": "admin", "name": name, "password": password}).encode()
    try:
        resp = opener.open(request.Request(f"{url}/login", data=body), timeout=30)
        final_url = resp.geturl()
    except error.URLError as e:
        fail(f"cannot reach portal: {e}")
    if "/login" in final_url:
        fail("admin login rejected (check FEMIS_ADMIN_* credentials)")
    print("portal login OK")

    # --- 3. download + validate -----------------------------------------
    try:
        resp = opener.open(f"{url}/api/admin/export", timeout=120)
        blob = resp.read()
    except error.HTTPError as e:
        fail(f"export failed: HTTP {e.code} {e.reason}")
    if blob[:16] != b"SQLite format 3\x00":
        fail(f"export is not a SQLite database: {blob[:60]!r}")
    staging = BACKUPS / f"femis_download-{ts}.db"
    staging.write_bytes(blob)
    con = sqlite3.connect(str(staging))
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        n_students = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        n_teachers = con.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
    finally:
        con.close()
    if str(integrity).lower() != "ok":
        staging.unlink(missing_ok=True)
        fail(f"integrity_check failed: {integrity}")
    print(f"download OK: {n_students} students, {n_teachers} teachers")

    # --- 4. atomic swap --------------------------------------------------
    incoming = DB.with_suffix(".db.incoming")
    shutil.move(str(staging), str(incoming))
    try:
        os.replace(incoming, DB)
    except PermissionError:
        incoming.unlink(missing_ok=True)
        fail("cannot replace local DB — stop the local dev server / tests first")
    print(f"local DB replaced -> {DB}")
    print(f"restore if needed: copy {backup} over {DB}")


if __name__ == "__main__":
    main()

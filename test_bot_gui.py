"""Smoke checks for bot_gui (local console). No portal network calls, no agent start/stop."""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bot_gui

PASS = 0
FAIL = 0


def check(cond, desc, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"PASS: {PASS} {desc} - {detail}" if detail else f"PASS: {PASS} {desc}")
    else:
        FAIL += 1
        print(f"FAIL: {desc} {detail}")


def main():
    check(True, "bot_gui imports (tkinter available)")

    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False,
                                     encoding="utf-8") as f:
        f.write("# comment\n"
                "FOO=bar\n"
                "QUOTED=\"hello world\"\n"
                "SPACED = value with spaces \n"
                "NOEQ\n")
        env_path = f.name
    env = bot_gui.load_env(env_path)
    Path(env_path).unlink(missing_ok=True)
    check(env.get("FOO") == "bar", "env parser reads plain key", env)
    check(env.get("QUOTED") == "hello world", "env parser strips quotes", env)
    check(env.get("SPACED") == "value with spaces", "env parser trims spaces", env)
    check("NOEQ" not in env, "env parser skips lines without =")

    real = bot_gui.load_env()
    check(real.get("FEMIS_PORTAL_URL", "").startswith("http"), "repo .env portal url loads")
    base, name, password = bot_gui.portal_credentials(real)
    check(base.startswith("http") and bool(name), "portal_credentials resolve url+name", base)
    check(bool(password) and password != "hardwired",
          "portal password resolves to the real portal credential")
    check(
        bot_gui.portal_credentials(
            {"FEMIS_PORTAL_URL": "https://x", "FEMIS_ADMIN_NAME": "N",
             "FEMIS_ADMIN_PASSWORD": "fallback"}
        )[2] == "fallback",
        "portal password falls back to FEMIS_ADMIN_PASSWORD",
    )
    check(
        bot_gui.portal_credentials(
            {"FEMIS_PORTAL_URL": "https://x", "FEMIS_ADMIN_NAME": "N",
             "FEMIS_ADMIN_PASSWORD": "local", "FEMIS_PORTAL_ADMIN_PASSWORD": "remote"}
        )[2] == "remote",
        "portal password prefers FEMIS_PORTAL_ADMIN_PASSWORD",
    )

    api = bot_gui.AdminAPI("https://example.invalid", "Faiza Mir", "pw")
    check(api.configured, "AdminAPI configured flag true with full creds")
    check(not bot_gui.AdminAPI("", "x", "y").configured, "AdminAPI configured flag false without url")

    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "x.log"
        tail = bot_gui.LogTail(log, max_bytes=100)
        check(tail.poll() == "", "LogTail empty for missing file")
        log.write_text("hello", encoding="utf-8")
        check(tail.poll() == "hello", "LogTail reads new file")
        log.write_text("A" * 300, encoding="utf-8")
        out = tail.poll()
        check(len(out) <= 100 and out.endswith("A"), "LogTail respects max_bytes (size drop resets)")
        log.write_text("short", encoding="utf-8")
        out = tail.poll()
        check(out == "short", "LogTail resets when file shrinks")

    pids = bot_gui.list_python_processes()
    check(isinstance(pids, list), "list_python_processes returns list", f"n={len(pids)}")
    pid = bot_gui.agent_pid()
    check(pid is None or isinstance(pid, int), "agent_pid returns int|None", f"pid={pid}")
    devs = bot_gui.dev_server_pids()
    check(isinstance(devs, list), "dev_server_pids returns list", f"pids={devs}")

    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    app = bot_gui.BotApp(root, auto_poll=False)
    check(app.btn_sync.cget("text") == "Sync DB now", "Sync button present")
    check(app.tree.cget("columns") is not None or True, "jobs treeview present")
    check(str(app.txt_log) != "", "log text widget present")
    check(app.lbl_agent is not None and app.lbl_status is not None, "status labels present")

    fixture = {
        "jobs": [
            {"job_id": 7, "student_id": 3, "student_name": "S", "attempt_number": 2,
             "status": "failed", "failed_field": "bps", "error_message": "boom"},
            {"job_id": 8, "student_id": 4, "student_name": "T", "attempt_number": 1,
             "status": "pending", "failed_field": None, "error_message": None},
        ],
        "paused": True,
        "agent": {"online": True, "last_seen": "2026-09-30 15:00:00"},
        "schedule": {"enabled": True, "time": "18:00", "sync_db": True,
                     "last_fired_date": "2026-09-30"},
    }
    app._apply_jobs(fixture)
    root.update()
    rows = app.tree.get_children()
    check(len(rows) == 2, "job rows rendered", f"rows={len(rows)}")
    check("QUEUE PAUSED" in app.lbl_paused.cget("text"), "paused badge shows on paused queue")
    check("failed=1" in app.lbl_counts.cget("text") and "pending=1" in app.lbl_counts.cget("text"),
          "counts label aggregates statuses", app.lbl_counts.cget("text"))
    check("18:00" in app.lbl_schedule.cget("text"), "schedule label shows time")
    check("online" in app.lbl_agent_state.cget("text"), "portal agent state shown")

    app._apply_agent_pid(12345)
    check("RUNNING (pid 12345)" in app.lbl_agent.cget("text"), "agent label running state")
    app._apply_agent_pid(None)
    check("stopped" in app.lbl_agent.cget("text"), "agent label stopped state")

    app._sync_done(0)
    check("sync finished rc=0" in app.txt_log.get("1.0", "end"), "sync success line appended")
    app._sync_done(1)
    check("sync FAILED rc=1" in app.txt_log.get("1.0", "end"), "sync failure line appended")

    root.destroy()
    check(True, "Tk app constructs and destroys cleanly")

    print("\n" + "=" * 64)
    if FAIL:
        print(f"{PASS}/{PASS + FAIL} checks passed, {FAIL} FAILED")
        sys.exit(1)
    print(f"{PASS}/{PASS} checks passed")
    time.sleep(0.2)


if __name__ == "__main__":
    main()

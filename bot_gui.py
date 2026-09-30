"""FemisBot local console - agent control, DB sync, queue operations (no web portal needed)."""
import http.cookiejar
import json
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "data" / "logs"
AGENT_OUT = LOGS / "agent-out.log"
AGENT_ERR = LOGS / "agent-err.log"
CREATE_NO_WINDOW = 0x08000000
PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
    "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }"
)


def load_env(path=ROOT / ".env"):
    env = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return env
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def list_python_processes():
    out = []
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", PS_LIST],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        return out
    for line in (proc.stdout or "").splitlines():
        if "|" not in line:
            continue
        pid_s, _, cmd = line.partition("|")
        try:
            out.append((int(pid_s.strip()), (cmd or "").strip()))
        except ValueError:
            continue
    return out


def agent_pid():
    for pid, cmd in list_python_processes():
        low = cmd.lower()
        if "src.main" in low and "--agent" in low:
            return pid
    return None


def dev_server_pids():
    hits = []
    for pid, cmd in list_python_processes():
        low = cmd.lower()
        if "femis-web" in low or "app.py" in low or "flask" in low:
            if "--agent" not in low and "src.main" not in low:
                hits.append(pid)
    return hits


def start_agent():
    LOGS.mkdir(parents=True, exist_ok=True)
    out = open(AGENT_OUT, "a", encoding="utf-8", errors="replace")
    err = open(AGENT_ERR, "a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.main", "--agent"],
            cwd=str(ROOT), stdout=out, stderr=err,
            creationflags=CREATE_NO_WINDOW,
        )
    finally:
        out.close()
        err.close()
    return proc.pid


def stop_agent(pid):
    proc = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True, text=True, timeout=20,
        creationflags=CREATE_NO_WINDOW,
    )
    return proc.returncode == 0, (proc.stdout or proc.stderr or "").strip()


def portal_credentials(env):
    base = (
        env.get("FEMIS_PORTAL_URL")
        or env.get("FEMIS_JOB_API_URL")
        or ""
    ).strip().rstrip("/")
    name = (env.get("FEMIS_PORTAL_ADMIN_NAME") or env.get("FEMIS_ADMIN_NAME") or "").strip()
    password = (
        env.get("FEMIS_PORTAL_ADMIN_PASSWORD") or env.get("FEMIS_ADMIN_PASSWORD") or ""
    ).strip()
    return base, name, password


class AdminAPI:
    def __init__(self, base_url, name, password):
        self.base_url = (base_url or "").rstrip("/")
        self.name = name
        self.password = password
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    @property
    def configured(self):
        return bool(self.base_url and self.name and self.password)

    def login(self):
        body = urllib.parse.urlencode(
            {"role": "admin", "name": self.name, "password": self.password}
        ).encode()
        req = urllib.request.Request(self.base_url + "/login", data=body, method="POST")
        with self.opener.open(req, timeout=30) as resp:
            return "/login" not in resp.geturl()

    def _call(self, method, path, payload=None, retried=False):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method, headers=headers
        )
        try:
            with self.opener.open(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            parsed = {}
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"error": raw[:300]}
            if e.code in (401, 403) and not retried and self.login():
                return self._call(method, path, payload, retried=True)
            return e.code, parsed
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return 0, {"error": str(e)}

    def get_jobs(self, limit=200):
        return self._call("GET", f"/api/admin/bot/jobs?limit={limit}")

    def pause(self):
        return self._call("POST", "/api/admin/bot/pause", {})

    def resume(self):
        return self._call("POST", "/api/admin/bot/resume", {})

    def retry(self, job_id):
        return self._call(
            "POST", f"/api/admin/bot/jobs/{job_id}/retry", {"refresh_snapshot": True}
        )

    def trigger_run(self, enqueue_locked):
        return self._call(
            "POST", "/api/admin/bot/run",
            {"sync_db": True, "enqueue_locked": bool(enqueue_locked)},
        )

    def queue_job(self, student_id):
        return self._call("POST", "/api/admin/bot/jobs", {"student_id": int(student_id)})


class LogTail:
    def __init__(self, path, max_bytes=120000):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.text = ""

    def poll(self):
        try:
            size = self.path.stat().st_size
        except OSError:
            return self.text
        if size > self.max_bytes:
            with open(self.path, "rb") as f:
                f.seek(size - self.max_bytes)
                chunk = f.read()
        else:
            with open(self.path, "rb") as f:
                chunk = f.read()
        text = chunk.decode("utf-8", errors="replace")
        if text != self.text:
            self.text = text
        return self.text


class BotApp:
    def __init__(self, root, auto_poll=True):
        self.root = root
        self.q = queue.Queue()
        self.stop_evt = threading.Event()
        self.env = load_env()
        portal, admin_name, admin_password = portal_credentials(self.env)
        self.api = AdminAPI(portal, admin_name, admin_password)
        self.tail_out = LogTail(AGENT_OUT)
        self.tail_err = LogTail(AGENT_ERR)
        self.last_log_text = ""
        self._syncing = False
        self._build()
        self.root.after(200, self._drain)
        self.root.after(300, self._tick_logs)
        self.root.after(800, self._tick_status_now)
        if auto_poll:
            self.root.after(500, self._start_poller)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self):
        self.root.title("FemisBot Local Console")
        self.root.geometry("1120x840")
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        self.lbl_portal = ttk.Label(
            top, text=f"Portal: {self.api.base_url or '(not configured)'}"
        )
        self.lbl_portal.pack(side="left")
        self.lbl_refresh = ttk.Label(top, text="")
        self.lbl_refresh.pack(side="right")

        agent = ttk.LabelFrame(self.root, text="Bot agent", padding=10)
        agent.pack(fill="x", padx=10, pady=(0, 6))
        self.lbl_agent = ttk.Label(agent, text="agent: checking...")
        self.lbl_agent.pack(side="left")
        ttk.Button(agent, text="Start agent", command=self.do_start_agent).pack(
            side="left", padx=(14, 4)
        )
        ttk.Button(agent, text="Stop agent", command=self.do_stop_agent).pack(
            side="left", padx=4
        )
        ttk.Button(agent, text="Refresh", command=self.do_status_refresh).pack(
            side="left", padx=4
        )
        ttk.Button(agent, text="Open logs folder", command=self.do_open_logs).pack(
            side="right"
        )

        sync = ttk.LabelFrame(self.root, text="Database sync (portal -> local)", padding=10)
        sync.pack(fill="x", padx=10, pady=(0, 6))
        self.btn_sync = ttk.Button(sync, text="Sync DB now", command=self.do_sync)
        self.btn_sync.pack(side="left")
        ttk.Label(
            sync,
            text="  The agent also syncs automatically before every run.",
        ).pack(side="left")
        self.lbl_devwarn = ttk.Label(sync, text="", foreground="#a45a00")
        self.lbl_devwarn.pack(side="right")

        queue_frame = ttk.LabelFrame(self.root, text="Job queue (via portal admin API)", padding=10)
        queue_frame.pack(fill="x", padx=10, pady=(0, 6))
        self.lbl_agent_state = ttk.Label(queue_frame, text="agent: ?")
        self.lbl_agent_state.pack(side="left", padx=(0, 10))
        self.lbl_paused = ttk.Label(queue_frame, text="queue: ?")
        self.lbl_paused.pack(side="left", padx=(0, 10))
        self.lbl_schedule = ttk.Label(queue_frame, text="schedule: ?")
        self.lbl_schedule.pack(side="left", padx=(0, 10))
        self.lbl_counts = ttk.Label(queue_frame, text="jobs: ?")
        self.lbl_counts.pack(side="left")

        actions = ttk.Frame(self.root, padding=(10, 0))
        actions.pack(fill="x")
        ttk.Button(actions, text="Pause queue", command=self.do_pause).pack(side="left")
        ttk.Button(actions, text="Resume queue", command=self.do_resume).pack(side="left", padx=4)
        self.var_enqueue = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            actions, text="enqueue locked students", variable=self.var_enqueue
        ).pack(side="left", padx=(10, 4))
        ttk.Button(actions, text="Trigger run", command=self.do_trigger).pack(side="left")
        ttk.Button(actions, text="Retry selected", command=self.do_retry).pack(
            side="left", padx=(10, 4)
        )
        ttk.Button(actions, text="Refresh jobs", command=self.do_refresh_jobs).pack(
            side="left", padx=4
        )
        self.ent_student = ttk.Entry(actions, width=8)
        self.ent_student.pack(side="left", padx=(10, 2))
        ttk.Button(actions, text="Queue job", command=self.do_queue_job).pack(side="left")

        jobs_frame = ttk.Frame(self.root, padding=(10, 6))
        jobs_frame.pack(fill="both", expand=False)
        cols = ("job", "student", "attempt", "status", "field", "error")
        self.tree = ttk.Treeview(jobs_frame, columns=cols, show="headings", height=9)
        headings = {
            "job": ("Job", 60), "student": ("Student", 170), "attempt": ("Att", 45),
            "status": ("Status", 85), "field": ("Failed field", 140),
            "error": ("Error / progress", 520),
        }
        for col, (title, width) in headings.items():
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w")
        scroll = ttk.Scrollbar(jobs_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        log_frame = ttk.LabelFrame(self.root, text="Agent log (auto-tail)", padding=6)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(4, 6))
        self.txt_log = tk.Text(
            log_frame, height=14, wrap="none", state="disabled",
            font=("Consolas", 9),
        )
        self.txt_log.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")

        self.lbl_status = ttk.Label(
            self.root, text="ready", padding=(10, 4), relief="sunken", anchor="w"
        )
        self.lbl_status.pack(fill="x", side="bottom")

        if not self.api.configured:
            self.set_status("FEMIS_PORTAL_URL / FEMIS_ADMIN_* not set in .env")

    def set_status(self, text):
        self.lbl_status.configure(text=time.strftime("%H:%M:%S  ") + text)

    def _post(self, fn, *args):
        def worker():
            try:
                self.q.put(("msg", fn(*args)))
            except Exception as e:
                self.q.put(("msg", f"error: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "msg":
                    self.set_status(str(payload))
                elif kind == "jobs":
                    self._apply_jobs(payload)
                elif kind == "sync_line":
                    self._append_sync(payload)
                elif kind == "sync_done":
                    self._sync_done(payload)
                elif kind == "agent_pid":
                    self._apply_agent_pid(payload)
        except queue.Empty:
            pass
        self.root.after(250, self._drain)

    def _start_poller(self):
        def loop():
            while not self.stop_evt.is_set():
                if self.api.configured:
                    status, data = self.api.get_jobs(200)
                    if status == 200:
                        self.q.put(("jobs", data))
                    else:
                        self.q.put(("msg", f"jobs fetch failed: {data.get('error')}"))
                self.q.put(("agent_pid", agent_pid()))
                self.stop_evt.wait(8)
        threading.Thread(target=loop, daemon=True).start()

    def _apply_jobs(self, data):
        jobs = data.get("jobs") or []
        counts = {}
        for j in jobs:
            st = str(j.get("status") or "?")
            counts[st] = counts.get(st, 0) + 1
        counts_txt = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        self.lbl_counts.configure(text=f"jobs: {counts_txt}")
        agent = data.get("agent") or {}
        seen = str(agent.get("last_seen") or "")
        self.lbl_agent_state.configure(
            text=f"portal sees agent: {'online' if agent.get('online') else 'offline'} ({seen})"
        )
        self.lbl_paused.configure(
            text=("QUEUE PAUSED" if data.get("paused") else "queue: running"),
            foreground=("#b00000" if data.get("paused") else "#006600"),
        )
        sched = data.get("schedule") or {}
        if sched.get("enabled"):
            self.lbl_schedule.configure(
                text=f"schedule: {sched.get('time')} sync={sched.get('sync_db')} "
                     f"fired={sched.get('last_fired_date') or '-'}"
            )
        else:
            self.lbl_schedule.configure(text="schedule: off")
        selected = None
        sel = self.tree.selection()
        if sel:
            selected = sel[0]
        self.tree.delete(*self.tree.get_children())
        for j in jobs[:40]:
            iid = str(j.get("job_id") or j.get("id"))
            err = (j.get("error_message") or "")[:160]
            self.tree.insert(
                "", "end", iid=iid, values=(
                    iid,
                    j.get("student_name") or j.get("student_id"),
                    j.get("attempt_number"),
                    j.get("status"),
                    j.get("failed_field") or "",
                    err,
                )
            )
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
        self.lbl_refresh.configure(
            text="portal data refreshed " + time.strftime("%H:%M:%S")
        )

    def _apply_agent_pid(self, pid):
        if pid:
            self.lbl_agent.configure(text=f"agent: RUNNING (pid {pid})",
                                     foreground="#006600")
        else:
            self.lbl_agent.configure(text="agent: stopped", foreground="#666666")

    def _tick_status_now(self):
        self._post(
            lambda: (
                f"agent pid {agent_pid()}" if agent_pid() else "agent stopped"
            )
        )
        self.root.after(5000, self._tick_status_now)

    def _tick_logs(self):
        out_text = self.tail_out.poll()
        err_text = self.tail_err.poll()
        if out_text or err_text:
            combined = ""
            if out_text:
                combined += out_text
            if err_text:
                if combined and not combined.endswith("\n"):
                    combined += "\n"
                combined += "--- agent-err.log ---\n" + err_text
            if combined != self.last_log_text:
                self.last_log_text = combined
                lines = combined.splitlines()[-600:]
                self.txt_log.configure(state="normal")
                self.txt_log.delete("1.0", "end")
                self.txt_log.insert("1.0", "\n".join(lines))
                self.txt_log.see("end")
                self.txt_log.configure(state="disabled")
        self.root.after(2500, self._tick_logs)

    def do_status_refresh(self):
        def work():
            pid = agent_pid()
            return "agent running (pid %s)" % pid if pid else "agent stopped"
        self._post(work)

    def do_start_agent(self):
        if agent_pid():
            self.set_status("agent already running")
            return
        try:
            pid = start_agent()
        except OSError as e:
            self.set_status(f"start failed: {e}")
            return
        self.set_status(f"agent started (pid {pid}) - polling portal every 20s")

    def do_stop_agent(self):
        pid = agent_pid()
        if not pid:
            self.set_status("agent not running")
            return
        ok, detail = stop_agent(pid)
        self.set_status(f"agent stopped (pid {pid})" if ok else f"stop failed: {detail}")
        self._apply_agent_pid(None)

    def do_open_logs(self):
        LOGS.mkdir(parents=True, exist_ok=True)
        try:
            import os
            os.startfile(str(LOGS))
        except OSError as e:
            self.set_status(f"cannot open logs folder: {e}")

    def do_sync(self):
        if self._syncing:
            self.set_status("sync already running")
            return
        pids = dev_server_pids()
        if pids:
            proceed = messagebox.askyesno(
                "Local dev server running",
                "Detected local dev server (pid %s). Sync replaces the local DB and "
                "Windows may block it while the server holds the file.\n\n"
                "Stop the dev server first, or continue anyway?" % ", ".join(map(str, pids)),
            )
            if not proceed:
                self.set_status("sync cancelled (dev server running)")
                return
        self._syncing = True
        self.btn_sync.configure(state="disabled")
        self._append_sync("=== sync started %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"))

        def worker():
            try:
                proc = subprocess.Popen(
                    [sys.executable, str(ROOT / "tools" / "sync_from_portal.py")],
                    cwd=str(ROOT),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=CREATE_NO_WINDOW,
                )
                for line in proc.stdout:
                    self.q.put(("sync_line", line.rstrip("\n")))
                proc.wait(timeout=660)
                self.q.put(("sync_done", proc.returncode))
            except Exception as e:
                self.q.put(("sync_line", f"error: {e}"))
                self.q.put(("sync_done", -1))
        threading.Thread(target=worker, daemon=True).start()

    def _append_sync(self, line):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", line + "\n")
        self.txt_log.see("end")
        total = int(self.txt_log.index("end-1c").split(".")[0])
        if total > 900:
            self.txt_log.delete("1.0", f"{total - 700}.0")
        self.txt_log.configure(state="disabled")

    def _sync_done(self, rc):
        self._syncing = False
        self.btn_sync.configure(state="normal")
        self._append_sync(
            "=== sync finished rc=%s ===" % rc
            if rc == 0
            else "=== sync FAILED rc=%s (see ERROR line above) ===" % rc
        )
        self.set_status("DB sync OK" if rc == 0 else f"DB sync FAILED (rc={rc})")

    def do_pause(self):
        self._post(lambda: "pause: %s" % (self.api.pause(),))

    def do_resume(self):
        self._post(lambda: "resume: %s" % (self.api.resume(),))

    def do_trigger(self):
        def work():
            status, data = self.api.trigger_run(self.var_enqueue.get())
            if status == 200 and data.get("ok"):
                if data.get("already_requested"):
                    return "run already requested (waiting for agent)"
                return "run requested - agent will sync DB then drain the queue"
            return f"trigger failed: {data.get('error') or data}"
        self._post(work)

    def do_retry(self):
        sel = self.tree.selection()
        if not sel:
            self.set_status("select a job row first")
            return
        job_id = sel[0]
        if not messagebox.askyesno("Retry job", f"Requeue job {job_id} (fresh snapshot)?"):
            return

        def work():
            status, data = self.api.retry(int(job_id))
            if status in (200, 201) and data.get("ok"):
                return f"job {job_id} requeued (attempt {data.get('job', {}).get('attempt_number')})"
            return f"retry failed: {data.get('error') or data}"
        self._post(work)

    def do_queue_job(self):
        raw = self.ent_student.get().strip()
        if not raw.isdigit():
            self.set_status("enter a numeric student id")
            return
        student_id = int(raw)

        def work():
            status, data = self.api.queue_job(student_id)
            if status in (200, 201) and data.get("ok"):
                return f"job queued for student {student_id}"
            return f"queue job failed: {data.get('error') or data}"
        self._post(work)

    def do_refresh_jobs(self):
        def work():
            status, data = self.api.get_jobs(200)
            if status == 200:
                self.q.put(("jobs", data))
                return "jobs refreshed"
            return f"jobs fetch failed: {data.get('error')}"
        threading.Thread(target=work, daemon=True).start()

    def _on_close(self):
        self.stop_evt.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    BotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

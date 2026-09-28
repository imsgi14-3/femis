"""HTTP client for the Phase 3B.4 bot-job API (stdlib urllib only).

Used by the bot in --jobs mode: claim -> snapshot, heartbeat, progress,
complete. Fails closed when FEMIS_BOT_TOKEN is not configured. Network or
transport problems never raise: they return (0, {"error_code": "api_unreachable"})
so the caller (job runner) can classify and record a structured failure.

Endpoints (contract: femis-web/job_api.py):
  POST /api/jobs/claim          {claimed_by, job_id?}         -> ok+job+student_snapshot
  POST /api/jobs/<id>/heartbeat {claimed_by, claim_generation} -> ok+job+lease_seconds+heartbeat_seconds
  POST /api/jobs/<id>/progress  {claimed_by, claim_generation, current_tab?,
                                 last_completed_tab?, current_field?, detail?}
  POST /api/jobs/<id>/complete  {claimed_by, claim_generation, outcome, ...}
"""
import json
import os
import urllib.error
import urllib.request

from src.utils.logger import setup_logger

logger = setup_logger("job_api_client")


class JobApiClientError(ValueError):
    """Fail-closed configuration error (missing token/URL)."""


class JobApiClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 8.0):
        url = (base_url or os.environ.get("FEMIS_JOB_API_URL") or "").strip() or "http://127.0.0.1:5000"
        tok = (token if token is not None else os.environ.get("FEMIS_BOT_TOKEN") or "").strip()
        if not tok:
            # Fail closed: never run job mode without the bot machine token.
            raise JobApiClientError("FEMIS_BOT_TOKEN is not configured (job API fails closed).")
        self.base_url = url.rstrip("/")
        self.token = tok
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        data = json.dumps(payload, default=str).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Bot-Token": self.token,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(body) if body else {}
                except ValueError:
                    return resp.status, {"ok": False, "error": "Non-JSON response.", "error_code": "bad_response"}
                if not isinstance(parsed, dict):
                    parsed = {"ok": False, "error": "Unexpected response shape.", "error_code": "bad_response"}
                return resp.status, parsed
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else {}
            except ValueError:
                parsed = {"ok": False, "error": body[:300], "error_code": "bad_response"}
            if not isinstance(parsed, dict):
                parsed = {"ok": False, "error": str(parsed), "error_code": "bad_response"}
            return e.code, parsed
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.warning(f"Job API unreachable: {path} -> {e}")
            return 0, {"ok": False, "error": str(e), "error_code": "api_unreachable"}

    def claim(self, claimed_by: str, job_id: int | None = None) -> tuple[int, dict]:
        payload: dict = {"claimed_by": claimed_by}
        if job_id is not None:
            payload["job_id"] = job_id
        return self._post("/api/jobs/claim", payload)

    def heartbeat(self, job_id: int, claimed_by: str, claim_generation: int) -> tuple[int, dict]:
        return self._post(
            f"/api/jobs/{job_id}/heartbeat",
            {"claimed_by": claimed_by, "claim_generation": claim_generation},
        )

    def progress(
        self,
        job_id: int,
        claimed_by: str,
        claim_generation: int,
        current_tab: int | None = None,
        last_completed_tab: int | None = None,
        current_field: str | None = None,
        detail: str | None = None,
    ) -> tuple[int, dict]:
        payload: dict = {"claimed_by": claimed_by, "claim_generation": claim_generation}
        if current_tab is not None:
            payload["current_tab"] = current_tab
        if last_completed_tab is not None:
            payload["last_completed_tab"] = last_completed_tab
        if current_field:
            payload["current_field"] = current_field
        if detail:
            payload["detail"] = detail
        return self._post(f"/api/jobs/{job_id}/progress", payload)

    def complete(self, job_id: int, claimed_by: str, claim_generation: int, result: dict) -> tuple[int, dict]:
        payload = dict(result)
        payload["claimed_by"] = claimed_by
        payload["claim_generation"] = claim_generation
        return self._post(f"/api/jobs/{job_id}/complete", payload)

    # --- agent control plane (src/main.py --agent mode) ---

    def agent_heartbeat(self) -> tuple[int, dict]:
        """Liveness stamp for the dashboard 'Agent online' badge."""
        return self._post("/api/bot/agent/heartbeat", {})

    def agent_poll(self, local_time: str) -> tuple[int, dict]:
        """Ask the portal whether a manual/scheduled run should start now.

        Consumes a pending manual request at dispatch; schedules fire once per
        agent-local day (server compares wall clock HH:MM, agent sends local time).
        """
        return self._post("/api/bot/agent/poll", {"local_time": local_time})

    def agent_run_complete(self, summary: dict) -> tuple[int, dict]:
        """Report run results into the dashboard run history (last 10)."""
        return self._post("/api/bot/agent/run-complete", summary)

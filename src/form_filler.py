import asyncio
import re
import yaml
from datetime import datetime
from pathlib import Path
from playwright.async_api import Page
from src.utils.logger import setup_logger
from src.utils.validators import format_cnic, format_mobile

logger = setup_logger("form_filler")

FIELD_MAP_PATH = Path(__file__).parent.parent / "config" / "field_mapping.yaml"

TAB_IDS = [
    ("Personal Details", "tab-nav-personal"),
    ("Parents / Guardian", "tab-nav-parents"),
    ("Educational Details", "tab-nav-education"),
    ("Emergency Contact", "tab-nav-emergency"),
    ("IDPs Details", "tab-nav-idps"),
    ("Health Details", "tab-nav-health"),
    ("Digital Access", "tab-nav-digital"),
]

# Portal name aliases when source_field != portal input[name]
PORTAL_NAME_ALIASES = {
    "same_address": "same_as_permanent_address",
    "siblings_same": "siblings_same_institution",
    "refugee_card": "refugee_card_number",
    "other_conditions": "other_medical_condition",
    "hearing_aid_details": "hearing_aid_details",
    "achievement_details": "cocurricular_details",
    "last_class_result": "result_percentage",
    "last_institution_other": "last_other_institution",
    "primary_education_completion_years": "primary_education_completion_years",
    "digital_device_type": "digital_device_type[]",
    "disability_types": "disability_types[]",
}

# Portal rejects mixed-case names: "Please enter only capital alphabets"
CAPITAL_NAME_SOURCES = {
    "name",
    "father_name",
    "mother_name",
    "guardian_name",
    "emergency_name",
    "previous_school_name",
}


LIST_URL = "https://femis.fde.gov.pk/students"
CREATE_URL = "https://femis.fde.gov.pk/students/create"


class FormFiller:
    """Fills the FEMIS SPA form by clicking tabs and filling fields by name/id."""

    def __init__(self):
        self.field_map = self._load_field_map()
        self._dialog_messages: list[str] = []
        self.form_mode: str = "create"
        self._just_filled: bool = False

    def _load_field_map(self) -> dict:
        with open(FIELD_MAP_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def attach_dialog_handler(self, page: Page):
        """Capture native JS dialogs (validation alerts) during fill/submit."""
        self._dialog_messages = []

        async def _on_dialog(dialog):
            msg = dialog.message
            self._dialog_messages.append(msg)
            logger.warning(f"Dialog: {msg[:200]}")
            try:
                await dialog.accept()
            except Exception:
                pass

        page.on("dialog", _on_dialog)

    async def open_form(self, page: Page, student_data: dict) -> str:
        """Open create or edit form.

        Portal search only works on name/class (not CNIC). Flow:
        1. Search list by student name
        2. Read CNIC/B-Form from visible result row(s)
        3. Open edit only when CNIC matches; else create
        """
        b_form = str(student_data.get("b_form") or "").strip()
        name = str(student_data.get("name") or student_data.get("student_name") or "").strip()
        self.form_mode = "create"
        if not name:
            await page.goto(CREATE_URL, wait_until="networkidle")
            await asyncio.sleep(1.5)
            return "create"

        try:
            await page.goto(LIST_URL, wait_until="networkidle")
            await asyncio.sleep(1.5)
            filled = False
            for sel in (
                "input[name='search']",
                "input[type='search']",
                "#search",
                ".dataTables_filter input",
            ):
                loc = page.locator(sel).first
                if await loc.count() == 0 or not await loc.is_visible():
                    continue
                await loc.fill(name)
                await loc.press("Enter")
                await asyncio.sleep(2.5)
                filled = True
                break
            if not filled:
                logger.warning("open_form: no search input on list page")

            # Scan result rows: match name, then verify CNIC on the same row
            result = await page.evaluate(
                """([name, bf]) => {
                    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toUpperCase();
                    const nameN = norm(name);
                    const bfDigits = (bf || '').replace(/\\D/g, '');
                    const rows = Array.from(document.querySelectorAll('table tr, .table tr, tr'));
                    const hits = [];
                    for (const row of rows) {
                        const text = row.innerText || '';
                        if (!text || !norm(text).includes(nameN)) continue;
                        const rowDigits = (text.replace(/\\D/g, ''));
                        const a = row.querySelector(
                            'a[href*="/students/"][href*="edit"], a[href*="/students/"]'
                        );
                        if (!a) continue;
                        const href = a.getAttribute('href') || '';
                        if (!href || href.endsWith('/students') || href.includes('/create')) continue;
                        hits.push({
                            href: a.href,
                            rowText: text.replace(/\\s+/g, ' ').trim(),
                            cnicMatch: bfDigits.length >= 6 && rowDigits.includes(bfDigits),
                            hasBf: bfDigits.length >= 6,
                        });
                    }
                    // Prefer CNIC match; else single name hit; else first hit
                    if (!hits.length) return null;
                    const exact = hits.filter(h => h.cnicMatch);
                    if (exact.length === 1) return exact[0];
                    if (hits.length === 1) return hits[0];
                    if (exact.length > 1) return exact[0];
                    return hits[0];
                }""",
                [name, b_form],
            )

            if result and result.get("href"):
                edit_url = result["href"]
                row_text = result.get("rowText", "")
                cnic_ok = bool(result.get("cnicMatch"))
                if b_form and not cnic_ok and result.get("hasBf"):
                    logger.warning(
                        f"Name matched but CNIC differs (want {b_form}); row={row_text!r}. Opening create."
                    )
                else:
                    logger.info(
                        f"Found existing student (name={name!r}, cnic_match={cnic_ok}), "
                        f"opening edit: {edit_url}"
                    )
                    await page.goto(edit_url, wait_until="networkidle")
                    await asyncio.sleep(2)
                    self.form_mode = "edit"
                    return "edit"
        except Exception as e:
            logger.warning(f"open_form list search failed: {e}")

        logger.info(f"No portal match for name={name!r}; opening create")
        await page.goto(CREATE_URL, wait_until="networkidle")
        await asyncio.sleep(1.5)
        return "create"

    async def _recover_duplicate(self, page: Page, student_data: dict | None) -> bool:
        """On 422 b_form already taken, switch to the existing portal record's edit form."""
        if not student_data:
            return False
        body_hit = False
        for a in (getattr(self, "_last_api", None) or []):
            if a.get("status") == 422 and "already been taken" in (a.get("body") or "").lower():
                body_hit = True
                break
        if not body_hit:
            ui = await self._capture_ui_error(page)
            if "already been taken" not in (ui or "").lower() and "b-form" not in (ui or "").lower():
                return False
        logger.warning("Duplicate b_form on portal — switching to edit mode")
        try:
            mode = await self.open_form(page, student_data)
            return mode == "edit"
        except Exception as e:
            logger.error(f"Duplicate recovery failed: {e}")
            return False

    async def fill_student_form(self, page: Page, student_data: dict) -> bool:
        logger.info(f"Filling form for: {student_data.get('name') or student_data.get('student_name', 'Unknown')}")
        self._attach_save_listeners(page)
        self.student_data = student_data
        self._just_filled = False

        probe_edit = self.form_mode == "edit"
        if probe_edit:
            logger.info("Edit mode: probing Save & Next to find first incomplete tab...")

        fill_from = 1
        if probe_edit:
            fill_from = await self._probe_incomplete_tab(page)

        for i, (tab_name, tab_id) in enumerate(TAB_IDS, 1):
            if probe_edit and i < fill_from:
                logger.info(f"--- Tab {i}/7: {tab_name} (already valid — skip fill, still learn) ---")
                if await self._click_tab(page, i, tab_name, tab_id):
                    await self._learn_unmapped_fields(page, i)
                continue

            logger.info(f"--- Tab {i}/7: {tab_name} ---")
            if not await self._click_tab(page, i, tab_name, tab_id):
                continue

            await self._fill_tab_fields(page, i, student_data)
            await self._learn_unmapped_fields(page, i)

            if i < 7:
                result = await self._save_next(page, i)
                if not result.get("ok") and probe_edit:
                    # Retry once after light defaults — re-open the same tab first
                    # because Save may have advanced the wizard even on failure.
                    try:
                        await self._click_tab(page, i, tab_name, tab_id)
                        await self._fill_default_required(page, student_data)
                        await self._learn_unmapped_fields(page, i)
                    except Exception:
                        pass
                    result = await self._save_next(page, i)
                if not result.get("ok"):
                    await self._learn_unmapped_fields(page, i, result.get("errors") or [])
                    # Recover wizard position if Save advanced past us
                    if i < 7:
                        await self._click_tab(page, i, tab_name, tab_id)

        # Persist tab 7 (no Save & Next on last step)
        try:
            if await self._force_save(page):
                logger.info("Force-save after final tab: OK")
            else:
                logger.warning("Force-save after final tab: failed")
        except Exception as e:
            logger.warning(f"Force-save after final tab error: {e}")

        logger.info("All tabs filled." if fill_from <= 7 else "Edit probe: all tabs already valid.")
        self._just_filled = True
        return True

    async def _click_tab(self, page: Page, tab_num: int, tab_name: str, tab_id: str) -> bool:
        try:
            tab_loc = page.locator(f"#{tab_id}").first
            if await tab_loc.count() > 0:
                await tab_loc.click(timeout=5000)
            else:
                await page.get_by_role("tab", name=tab_name).click(timeout=5000)
            await asyncio.sleep(1)
            return True
        except Exception as e:
            logger.warning(f"Tab click failed: {e}")
            return False

    async def _probe_incomplete_tab(self, page: Page) -> int:
        """In edit mode, Save & Next each tab without filling.

        Returns the first tab number (1-based) that fails validation
        (or 7 if all of 1–6 are already valid).
        """
        for i, (tab_name, tab_id) in enumerate(TAB_IDS, 1):
            if i >= 7:
                break
            if not await self._click_tab(page, i, tab_name, tab_id):
                return i
            result = await self._save_next(page, i, probe=True)
            # Save advances the wizard — return to the tab we probed before learn/fill.
            await self._click_tab(page, i, tab_name, tab_id)
            if result.get("ok"):
                logger.info(f"  Probe tab {i}: OK (already filled)")
                continue
            errs = result.get("errors") or []
            logger.warning(f"  Probe tab {i}: FAIL — filling from here. Errors: {errs[:6]}")
            await self._learn_unmapped_fields(page, i, errs)
            return i
        return 7

    async def _save_next(self, page: Page, tab_num: int, probe: bool = False) -> dict:
        """Click Save & Next and return {ok, errors, advanced, api}."""
        prefix = "Probe" if probe else "Save"
        save_btn = page.locator("#saveNextBtn, button:has-text('Save & Next')").first
        if await save_btn.count() == 0 or not await save_btn.is_visible():
            logger.warning(f"  {prefix}: Save & Next not visible on tab {tab_num}")
            return {"ok": False, "errors": ["Save & Next not visible"], "advanced": False, "api": []}

        active_before = await self._active_tab_id(page)
        # Measure empties on the CURRENT tab before Save advances the wizard.
        empty_required = await self._empty_required_on_tab(page)
        await self._preflight_save(page, tab_num)
        before = len(getattr(self, "_last_api", []) or [])
        try:
            await save_btn.click(timeout=5000)
            await asyncio.sleep(2.0)
            await self._handle_confirm(page)
        except Exception as e:
            logger.warning(f"  {prefix} click failed: {e}")
            return {"ok": False, "errors": [str(e)], "advanced": False, "api": [], "empty_required": empty_required}

        ui = await self._capture_ui_error(page)
        errs = await self._collect_errors(page)
        new_api = (getattr(self, "_last_api", None) or [])[before:]
        active_after = await self._active_tab_id(page)
        invalid_count = await self._count_invalid(page)

        real = []
        for e in list(errs) + ([ui] if ui else []):
            for part in str(e).split("|"):
                part = part.strip()
                if self._is_real_error(part) and part not in real:
                    real.append(part)

        api_fail = []
        for a in new_api:
            status = a.get("status", 0) or 0
            body = (a.get("body") or "").lower()
            if status >= 400 or "went wrong" in body or "already been taken" in body:
                api_fail.append(a)
                logger.warning(f"  Save API error {status} {a.get('url')} :: {(a.get('body') or '')[:300]}")

        advanced = bool(active_before) and active_before != active_after
        # Empties were measured on the pre-click tab; portal may still advance
        # the wizard UI while marking fields invalid — treat empties as failure.
        blocked = bool(empty_required) or invalid_count > 0
        ok = not real and not api_fail and not blocked
        if not new_api and not advanced and not probe and (real or blocked):
            ok = False
        # UI advanced or fields look filled but nothing hit the network:
        # values will vanish on reload — treat as failure so we retry/save hard.
        if not new_api and not probe and (advanced or not blocked):
            logger.warning(
                f"  {prefix} tab {tab_num}: NO network request — form did not persist "
                f"(advanced={advanced}). Filled values will be lost on reload."
            )
            if not probe:
                ok = False
                # Force the portal's own save handler / form submit once
                forced = await self._force_save(page)
                if forced:
                    await asyncio.sleep(1.5)
                    new_api = (getattr(self, "_last_api", None) or [])[before:]
                    if new_api:
                        logger.info(f"  Force-save produced {len(new_api)} request(s)")
                        ok = not any(
                            (a.get("status") or 0) >= 400 for a in new_api
                        ) and not blocked and not real
                    else:
                        # fetch may not hit Playwright response listener; force_save
                        # already confirmed HTTP success body
                        logger.info("  Force-save confirmed saved (no listener entry)")
                        ok = not blocked and not real
                else:
                    logger.warning("  Force-save failed")

        verb = "advanced" if advanced else "stayed"
        logger.info(
            f"  {prefix} tab {tab_num}: {'OK' if ok else 'FAIL'} "
            f"({verb}, errors={len(real)}, invalid={invalid_count}, "
            f"empty_req={empty_required[:6]}, api={len(new_api)})"
        )
        if real:
            logger.warning(f"  {prefix} errors: {real[:8]}")
        if empty_required:
            logger.warning(f"  {prefix} empty required: {empty_required[:12]}")
        return {
            "ok": ok,
            "errors": real or ([f"empty required: {empty_required[0]}"] if empty_required else []),
            "advanced": advanced,
            "api": new_api,
            "empty_required": empty_required,
        }

    async def _force_save(self, page: Page) -> bool:
        """Portal never POSTs on Save & Next (tab-only). Persist via edit update.

        Edit form loads with inputs disabled. Enable all fields, then
        POST multipart to form.action with Laravel _method=PUT.
        Returns True when a non-GET request was recorded on _last_api.
        """
        before = len(getattr(self, "_last_api", []) or [])
        try:
            result = await page.evaluate(
                """async () => {
                    const form = document.getElementById('studentForm') || document.querySelector('form[action*="/students/"]');
                    if (!form) return {ok: false, err: 'no form'};
                    form.querySelectorAll('input, select, textarea').forEach(el => {
                        el.disabled = false;
                        el.readOnly = false;
                    });
                    const action = form.action;
                    const body = new FormData(form);
                    if (!body.get('_method')) body.append('_method', 'PUT');
                    if (!body.get('_token')) {
                        const m = document.cookie.match(/(?:^|;\\s*)XSRF-TOKEN=([^;]+)/);
                        // Laravel also accepts meta csrf-token
                        const meta = document.querySelector('meta[name="csrf-token"]');
                        const tok = meta ? meta.getAttribute('content') : '';
                        if (tok) body.append('_token', tok);
                        else if (m) body.append('_token', decodeURIComponent(m[1]));
                    }
                    const headers = {};
                    const m2 = document.cookie.match(/(?:^|;\\s*)XSRF-TOKEN=([^;]+)/);
                    if (m2) headers['X-XSRF-TOKEN'] = decodeURIComponent(m2[1]);
                    headers['Accept'] = 'application/json';
                    try {
                        const r = await fetch(action, {
                            method: 'POST',
                            body,
                            credentials: 'same-origin',
                            headers,
                        });
                        const text = await r.text();
                        return {ok: r.ok, status: r.status, body: text.slice(0, 500), action};
                    } catch (e) {
                        return {ok: false, err: String(e), action};
                    }
                }"""
            )
            logger.info(
                f"  Force-save POST {result.get('status')} :: "
                f"{(result.get('body') or result.get('err') or '')[:300]}"
            )
            await asyncio.sleep(0.8)
            got = len(getattr(self, "_last_api", []) or []) > before
            # evaluate fetch is same-origin; Playwright may capture it as response.
            # If listener missed it but HTTP was ok, treat as saved.
            if result.get("ok") and "Saved successfully" in (result.get("body") or ""):
                return True
            return got or bool(result.get("ok"))
        except Exception as e:
            logger.warning(f"  Force-save failed: {e}")
            return False

    async def _count_invalid(self, page: Page) -> int:
        """Count real invalid controls on the ACTIVE pane only (ignore bare * markers)."""
        try:
            return await page.evaluate("""() => {
                const pane = (() => {
                    const candidates = Array.from(document.querySelectorAll(
                        '.tab-pane, [role="tabpanel"], .step-pane, .wizard-content'
                    ));
                    const active = candidates.find(p =>
                        p.classList.contains('active') ||
                        p.classList.contains('show') ||
                        p.getAttribute('aria-hidden') === 'false'
                    );
                    if (active) return active;
                    return candidates.find(p => p.offsetParent !== null) || document.body;
                })();
                let n = 0;
                pane.querySelectorAll('.is-invalid, .invalid-feedback, .text-danger').forEach(el => {
                    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!t || t === '*') return;
                    if (el.classList.contains('invalid-feedback') && !el.classList.contains('show') && !el.classList.contains('d-block')) return;
                    n++;
                });
                return n;
            }""")
        except Exception:
            return 0

    @staticmethod
    def _junk_label(label: str) -> bool:
        t = (label or "").strip().lower()
        if not t or len(t) < 2:
            return True
        return t in {
            "yes", "no", "ok", "empty", "select", "none", "null", "true", "false",
            "required", "field", "value", "option", "choose", "please select",
            "morning", "evening", "institution bus", "walk", "day scholar",
            "other", "others", "specify", "please specify",
        }

    async def _empty_required_on_tab(self, page: Page) -> list[str]:
        """Labels of required controls empty on the ACTIVE pane only."""
        try:
            raw = await page.evaluate("""() => {
                const candidates = Array.from(document.querySelectorAll(
                    '.tab-pane, [role="tabpanel"], .step-pane, .wizard-content'
                ));
                const pane = candidates.find(p =>
                        p.classList.contains('active') ||
                        p.classList.contains('show') ||
                        p.getAttribute('aria-hidden') === 'false'
                    ) ||
                    candidates.find(p => p.offsetParent !== null) ||
                    document.body;
                const out = [];
                const isVisible = (el) => {
                    try {
                        const st = window.getComputedStyle(el);
                        if (!st || st.display === 'none' || st.visibility === 'hidden') return false;
                        if (el.closest && el.closest('[hidden], .d-none')) return false;
                        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                    } catch (e) { return false; }
                };
                const labelFor = (el) => {
                    try {
                        const t = String(el.type || '');
                        if (t === 'radio' || t === 'checkbox') {
                            const fs = el.closest('fieldset');
                            if (fs) {
                                const leg = fs.querySelector('legend, .form-label, .control-label');
                                if (leg) {
                                    const lt = (leg.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '');
                                    if (lt) return lt;
                                }
                            }
                            const group = Array.from(document.querySelectorAll(`input[type="${t}"]`))
                                .filter(r => r && r.name === el.name);
                            for (const r of group) {
                                if (!r.id) continue;
                                const l = document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
                                if (!l) continue;
                                const p = l.closest('.form-group, .mb-3, .col, .row');
                                if (!p) continue;
                                const heading = p.querySelector(':scope > label, :scope > .form-label, :scope > legend');
                                if (heading && heading !== l) {
                                    const ht = (heading.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '');
                                    if (ht) return ht;
                                }
                            }
                            const wrap = el.closest('.form-group, .mb-3, .col, .row');
                            if (wrap) {
                                const direct = wrap.querySelector(':scope > label, :scope > .form-label, :scope > legend');
                                if (direct) {
                                    const dt = (direct.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '');
                                    if (dt) return dt;
                                }
                            }
                            return el.name || el.id || '';
                        }
                        if (el.id) {
                            const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                            if (l) return (l.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '');
                        }
                        const p = el.closest('.form-group, .mb-3, .col, .row, td');
                        if (p) {
                            const l = p.querySelector('label');
                            if (l) return (l.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '');
                        }
                    } catch (e) {}
                    return el.name || el.id || '';
                };
                const seen = new Set();
                (pane.querySelectorAll ? pane : document).querySelectorAll('input, select, textarea').forEach(el => {
                    try {
                        if (!el || !isVisible(el)) return;
                        const name = el.name || el.id || '';
                        const inputType = String(el.type || '');
                        if (!name || inputType === 'hidden' || inputType === 'file') return;
                        if (seen.has(name)) return;
                        let required = !!el.required || el.getAttribute('aria-required') === 'true';
                        if (inputType === 'radio') {
                            const group = Array.from(document.querySelectorAll('input[type="radio"]'))
                                .filter(r => r && r.name === name);
                            required = required || group.some(r => !!(r && r.required));
                            const any = group.some(r => r && r.checked);
                            if (required && !any) {
                                seen.add(name);
                                out.push(labelFor(el) || name);
                            }
                            return;
                        }
                        if (inputType === 'checkbox') {
                            if (required && !el.checked) {
                                seen.add(name);
                                out.push(labelFor(el) || name);
                            }
                            return;
                        }
                        if (!required) return;
                        const v = String(el.value == null ? '' : el.value).trim();
                        // Conditional portal fields: not required when parent flag is off
                        const nm = String(el.name || '');
                        if (nm === 'orphan_type') {
                            const orphan = document.querySelector('input[type="radio"][name="is_orphan"]:checked');
                            const yes = orphan && ['1','Yes','yes','true'].includes(String(orphan.value));
                            if (!yes) return;
                        }
                        if (nm === 'glass_prescription' || nm.includes('glass')) {
                            const glasses = document.querySelector('input[type="radio"][name="uses_glasses"]:checked');
                            const wears = glasses && ['1','Yes','yes','true'].includes(String(glasses.value));
                            if (!wears) return;
                        }
                        if (!v) {
                            seen.add(name);
                            out.push(labelFor(el) || name);
                        }
                    } catch (e) {}
                });
                return out;
            }""")
            if not isinstance(raw, list):
                return []
            junk = FormFiller._junk_label
            seen = set()
            out = []
            for lab in raw:
                s = str(lab or "").strip()
                if not s or junk(s):
                    continue
                key = s.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(s)
            return out
        except Exception:
            return []

    async def _active_tab_id(self, page: Page) -> str:
        try:
            return await page.evaluate("""() => {
                const a = document.querySelector('.nav-link.active, .nav-item .active, [role="tab"].active, .active.show');
                return a ? (a.id || (a.textContent || '').trim()) : '';
            }""")
        except Exception:
            return ""

    @staticmethod
    def _is_real_error(text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return False
        stripped = re.sub(r"[\s*|·•••\-–—]+", "", t)
        return bool(stripped)

    async def _learn_unmapped_fields(self, page: Page, tab_num: int, errors: list[str] | None = None):
        """Discover ALL portal controls on this tab (required + optional) and map any we lack."""
        try:
            if not isinstance(self.field_map, dict):
                self.field_map = self._load_field_map() or {}
            tab_key = next(
                (k for k in self.field_map if isinstance(k, str) and k.startswith(f"tab_{tab_num}_")),
                None,
            )
            if not tab_key or not isinstance(self.field_map.get(tab_key), dict):
                if tab_key:
                    self.field_map[tab_key] = {}
                else:
                    return
            known_labels, known_sources, known_portal = self._known_field_index(tab_key)

            # Every visible named control on the active tab pane (required or not)
            dom_fields = await page.evaluate("""() => {
                const out = [];
                const labelFor = (el) => {
                    try {
                        const t = String(el.type || '');
                        if (t === 'radio' || t === 'checkbox') {
                            const fs = el.closest('fieldset');
                            if (fs) {
                                const leg = fs.querySelector('legend, .form-label, .control-label');
                                if (leg) {
                                    const lt = (leg.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '');
                                    if (lt) return lt;
                                }
                            }
                            const group = Array.from(document.querySelectorAll(`input[type="${t}"]`))
                                .filter(r => r && r.name === el.name);
                            for (const r of group) {
                                if (!r.id) continue;
                                const l = document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
                                if (!l) continue;
                                const p = l.closest('.form-group, .mb-3, .col, .row');
                                if (!p) continue;
                                const heading = p.querySelector(':scope > label, :scope > .form-label, :scope > legend');
                                if (heading && heading !== l) {
                                    const ht = (heading.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '');
                                    if (ht) return ht;
                                }
                            }
                            const wrap = el.closest('.form-group, .mb-3, .col, .row');
                            if (wrap) {
                                const direct = wrap.querySelector(':scope > label, :scope > .form-label, :scope > legend');
                                if (direct) {
                                    const dt = (direct.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '');
                                    if (dt) return dt;
                                }
                            }
                            return el.name || el.id || '';
                        }
                        if (el.id) {
                            const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                            if (l) return (l.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '').trim();
                        }
                        const parent = el.closest('.form-group, .mb-3, .col-md-6, .col-md-4, .col-12, .col, .row, td, .input-group, .mb-2');
                        if (parent) {
                            const l = parent.querySelector('label');
                            if (l) return (l.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '').trim();
                        }
                        const prev = el.previousElementSibling;
                        if (prev && prev.tagName === 'LABEL') {
                            return (prev.innerText || '').replace(/\\s+/g, ' ').trim().replace(/\\s*\\*\\s*$/, '').trim();
                        }
                    } catch (e) {}
                    return '';
                };
                const isVisible = (el) => {
                    try {
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        if (el.closest && el.closest('[hidden], .d-none')) return false;
                        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                    } catch (e) { return false; }
                };
                const activePane = document.querySelector('.tab-pane.active, .tab-pane.show, [role="tabpanel"].active, [role="tabpanel"].show')
                    || document.querySelector('.tab-pane');
                const root = (activePane && activePane.querySelectorAll('input, select, textarea').length)
                    ? activePane
                    : document;

                root.querySelectorAll('input, select, textarea').forEach(el => {
                    try {
                        if (!el || !isVisible(el)) return;
                        const name = el.name || el.id || '';
                        const inputType = String(el.type || '');
                        if (!name || inputType === 'hidden') return;
                        if (inputType === 'file') return;

                        let kind = inputType || String(el.tagName || '').toLowerCase();
                        let required = !!(el.required) || el.getAttribute('aria-required') === 'true';
                        let options = [];
                        let value = '';

                        if (el.tagName === 'SELECT') {
                            kind = 'dropdown';
                            value = el.value || '';
                            options = Array.from(el.options || [])
                                .map(o => String((o && o.text) || '').trim())
                                .filter(t => t && !/^select\\b/i.test(t));
                            if (el.required) required = true;
                        } else if (inputType === 'radio') {
                            kind = 'radio';
                            let group = [];
                            try {
                                group = Array.from(document.querySelectorAll('input[type="radio"]'))
                                    .filter(r => r && r.name === name);
                            } catch (e) { group = []; }
                            required = required || group.some(r => !!(r && (r.required || r.getAttribute('aria-required') === 'true')));
                            const checkedOne = group.find(r => r && r.checked);
                            options = group.map(r => {
                                if (!r) return '';
                                if (r.value === '1' || r.value === '0') return r.value === '1' ? 'Yes' : 'No';
                                const rid = r.id;
                                if (rid) {
                                    try {
                                        const lab = document.querySelector(`label[for="${CSS.escape(rid)}"]`);
                                        if (lab) return (lab.innerText || '').trim();
                                    } catch (e) {}
                                }
                                return (r.value || '').trim();
                            }).filter(Boolean);
                            value = checkedOne ? (checkedOne.value || '') : '';
                        } else if (inputType === 'checkbox') {
                            kind = 'checkbox';
                            if (el.required) required = true;
                            value = el.checked ? '1' : '0';
                        } else {
                            kind = 'text';
                            value = el.value || '';
                        }

                        if (kind === 'email' || kind === 'tel' || kind === 'number' || kind === 'textarea') {
                            kind = 'text';
                        }

                        out.push({
                            name: String(name),
                            label: labelFor(el),
                            type: kind,
                            required: !!required,
                            options,
                            value: String(value || ''),
                            placeholder: String(el.placeholder || ''),
                            inputType,
                        });
                    } catch (e) {}
                });

                const byName = new Map();
                for (const f of out) {
                    if (!f || !f.name) continue;
                    const key = f.name;
                    if (!byName.has(key)) byName.set(key, f);
                    else if (f.required && !byName.get(key).required) byName.set(key, f);
                }
                return Array.from(byName.values());
            }""")

            if not isinstance(dom_fields, list):
                dom_fields = []

            # Validation labels => force required (skip junk like 'empty' / 'Yes')
            msg_labels = []
            for err in errors or []:
                if not err:
                    continue
                text = str(err)
                m = re.search(
                    r"(?:please\s+)?(?:select|enter|choose)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9 /&'’()\-]{2,60})",
                    text, re.I,
                )
                cand = m.group(1).strip(" .:-") if m else None
                if not cand:
                    m = re.search(r"([A-Za-z][A-Za-z0-9 /&'’()\-]{2,60}?)\s+(?:is\s+)?required", text, re.I)
                    cand = m.group(1).strip(" .:-") if m else None
                if cand and not self._junk_label(cand) and not cand.lower().startswith("empty required"):
                    msg_labels.append(cand)

            msg_required = {self._norm_label(x) for x in msg_labels}

            additions = []
            for f in dom_fields:
                if not isinstance(f, dict):
                    continue
                label = (str(f.get("label") or "").strip()) or (str(f.get("name") or "").strip())
                name = str(f.get("name") or "")
                if not label and not name:
                    continue
                if self._junk_label(label) and self._junk_label(name):
                    continue
                if name.lower() in ("empty", "undefined", "null") or label.lower() in ("empty", "undefined", "null"):
                    continue
                ftype = f.get("type") or "text"
                if ftype not in ("text", "dropdown", "radio", "checkbox", "date"):
                    ftype = "text"
                required = bool(f.get("required")) or self._norm_label(label) in msg_required

                if self._field_covered(label, name, known_labels, known_sources, known_portal):
                    if required and not self._is_required_in_map(label, name, tab_key):
                        if self._mark_required(tab_key, label, name):
                            additions.append(f"required=true :: {label or name}")
                    opts = f.get("options")
                    self._merge_options(tab_key, label, name, list(opts) if isinstance(opts, list) else [])
                    continue

                additions.append(
                    f"new {'required' if required else 'optional'} :: label={label!r} name={name!r} type={ftype}"
                )
                opts = f.get("options")
                self._add_field_to_map(
                    tab_key, label or name, name, ftype,
                    required=required,
                    options=list(opts) if isinstance(opts, list) else [],
                    placeholder=str(f.get("placeholder") or ""),
                )
                known_labels.add(self._norm_label(label))
                if name:
                    known_sources.add(name.lower())
                    known_portal.add(name.lower().replace("[]", ""))

            for label in msg_labels:
                if self._junk_label(label):
                    continue
                if self._field_covered(label, "", known_labels, known_sources, known_portal):
                    if not self._is_required_in_map(label, "", tab_key):
                        if self._mark_required(tab_key, label, ""):
                            additions.append(f"required=true (from validation) :: {label}")
                    continue
                additions.append(f"unmapped validation label :: {label!r}")
                self._add_field_to_map(tab_key, label, "", "text", required=True)

            if additions:
                logger.warning(f"  Updated field_mapping for tab {tab_num}: {additions}")
                self._save_field_map()
                self.field_map = self._load_field_map() or {}
        except Exception as e:
            logger.warning(f"  learn_unmapped_fields failed: {e}")

    def _merge_options(self, tab_key: str, label: str, name: str, options: list):
        """Attach discovered dropdown/radio options to an existing mapped field."""
        if not options:
            return
        nl = self._norm_label(label)
        nn = self._norm_label(name)

        def walk(node):
            if not isinstance(node, dict):
                return False
            if "type" in node and "label" in node:
                match = (nl and self._norm_label(node.get("label") or "") == nl) or (
                    nn and self._norm_label(node.get("source_field") or "") == nn
                )
                if match and node.get("type") in ("dropdown", "radio"):
                    existing = node.get("options") or []
                    merged = list(existing)
                    for o in options:
                        if o and o not in merged:
                            merged.append(o)
                    if merged != existing:
                        node["options"] = merged
                        return True
                return False
            changed = False
            for v in node.values():
                if isinstance(v, dict) and walk(v):
                    changed = True
            return changed

        if walk(self.field_map.get(tab_key) or {}):
            self._save_field_map()

    def _known_field_index(self, tab_key: str) -> tuple[set, set, set]:
        labels, sources, portals = set(), set(), set()
        tab_data = self.field_map.get(tab_key) or {}

        def walk(node):
            if not isinstance(node, dict):
                return
            if "type" in node and "label" in node:
                labels.add(str(node.get("label") or "").strip().lower())
                if node.get("source_field"):
                    sources.add(str(node["source_field"]).strip().lower())
                    portals.add(self._portal_name(node).strip().lower())
                return
            for v in node.values():
                walk(v)

        walk(tab_data)
        return labels, sources, portals

    @staticmethod
    def _norm_label(s: str) -> str:
        return re.sub(r"[\s_\-]+", " ", (s or "").strip().lower()).strip(" .:-")

    def _field_covered(self, label: str, name: str, labels: set, sources: set, portals: set) -> bool:
        nl = self._norm_label(label)
        nn = self._norm_label(name)
        if nl and nl in labels:
            return True
        if nn and (nn in sources or nn in portals or nn.replace("[]", "") in portals):
            return True
        # loose: label equals a known label ignoring punctuation
        if nl:
            for known in labels:
                if self._norm_label(known) == nl:
                    return True
        return False

    def _is_required_in_map(self, label: str, name: str, tab_key: str) -> bool:
        nl = self._norm_label(label)
        nn = self._norm_label(name)

        def walk(node):
            if not isinstance(node, dict):
                return None
            if "type" in node and "label" in node:
                if nl and self._norm_label(node.get("label") or "") == nl:
                    return node
                sf = self._norm_label(node.get("source_field") or "")
                if nn and sf == nn:
                    return node
                if nn and self._portal_name(node).strip().lower().replace("[]", "") == nn.replace("[]", ""):
                    return node
            for v in node.values():
                hit = walk(v)
                if hit is not None:
                    return hit
            return None

        cfg = walk(self.field_map.get(tab_key) or {})
        return bool(cfg and cfg.get("required"))

    def _mark_required(self, tab_key: str, label: str, name: str) -> bool:
        nl = self._norm_label(label)
        nn = self._norm_label(name)

        def walk(node):
            if not isinstance(node, dict):
                return False
            if "type" in node and "label" in node:
                match = False
                if nl and self._norm_label(node.get("label") or "") == nl:
                    match = True
                if nn and self._norm_label(node.get("source_field") or "") == nn:
                    match = True
                if match:
                    node["required"] = True
                    return True
            for v in node.values():
                if isinstance(v, dict) and walk(v):
                    return True
            return False

        return walk(self.field_map.get(tab_key) or {})

    def _add_field_to_map(
        self,
        tab_key: str,
        label: str,
        name: str,
        ctrl_type: str,
        required: bool = True,
        options: list | None = None,
        placeholder: str = "",
    ):
        """Append a new field entry under the first section of tab_key."""
        key = re.sub(r"[^a-z0-9]+", "_", self._norm_label(label or name)).strip("_") or "unknown_field"
        if not key or key == "unknown_field":
            if name:
                key = re.sub(r"\[\]$", "", name)
            else:
                return
        source = name or key

        type_map = {
            "radio": "radio",
            "checkbox": "checkbox",
            "select-one": "dropdown",
            "select": "dropdown",
            "email": "text",
            "tel": "text",
            "number": "text",
            "textarea": "text",
            "text": "text",
            "date": "date",
        }
        ftype = type_map.get((ctrl_type or "text").lower(), "text")
        entry = {
            "label": label or name or key,
            "type": ftype,
            "required": bool(required),
            "source_field": source,
            "note": "Auto-discovered from portal DOM (map source_field to DB column when known)",
        }
        if placeholder:
            entry["placeholder"] = placeholder
        if ftype == "radio":
            entry["options"] = list(options) if options else ["Yes", "No"]
        elif ftype == "dropdown" and options:
            entry["options"] = list(options)

        tab_data = self.field_map.setdefault(tab_key, {})
        # Prefer nested first section if present (tab_1 style); else flat under tab
        placed = False
        for sec_name, sec in list(tab_data.items()):
            if isinstance(sec, dict) and "type" not in sec and "label" not in sec:
                if key not in sec:
                    sec[key] = entry
                    placed = True
                    break
        if not placed and key not in tab_data:
            # Try flat (tab_5/6/7 style): only if values look like field configs or empty
            if not tab_data or all(isinstance(v, dict) and ("type" in v or "label" in v) for v in tab_data.values()):
                tab_data[key] = entry
            else:
                section = tab_data.setdefault("discovered_fields", {})
                if isinstance(section, dict):
                    section[key] = entry

    def _save_field_map(self):
        with open(FIELD_MAP_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.field_map, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        logger.info(f"  Wrote field updates to {FIELD_MAP_PATH}")

    async def _preflight_save(self, page: Page, tab_num: int):
        """Fix client-side blockers so Save & Next actually POSTs.

        Portal shows 'Please enter only capital alphabets' on mixed-case names
        and blocks the save handler (no network request).
        """
        try:
            fixed = await page.evaluate("""() => {
                const done = [];
                document.querySelectorAll('input[type="text"], input:not([type])').forEach(el => {
                    const n = (el.name || el.id || '').toLowerCase();
                    const isName = /(^|_)(name|student_name|father_name|mother_name|guardian_name)$/.test(n)
                        || n === 'name'
                        || /name/i.test(el.placeholder || '');
                    if (!isName || !el.value) return;
                    const up = el.value.replace(/[^A-Za-z .'-]/g, '').toUpperCase();
                    if (up && up !== el.value) {
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, up);
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        el.dispatchEvent(new Event('blur', {bubbles: true}));
                        done.push(`${el.name || el.id}: ${up}`);
                    }
                });
                // clear leftover invalid state on now-valid name fields
                document.querySelectorAll('input.is-invalid').forEach(el => {
                    const fb = el.parentElement && el.parentElement.querySelector('.invalid-feedback, .invalid-tooltip');
                    if (fb) fb.classList.remove('show', 'd-block');
                    el.classList.remove('is-invalid');
                });
                // Portal POST rejects ISO dates (500) — rewrite YYYY-MM-DD -> DD/MM/YYYY
                document.querySelectorAll('input').forEach(el => {
                    const v = el.value || '';
                    if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(v)) return;
                    const n = (el.name || el.id || '').toLowerCase();
                    if (!/date|dob|birth|admission/.test(n) && el.type !== 'date') return;
                    if (el.type === 'date') el.type = 'text';
                    const [y, m, d] = v.split('-');
                    const dmy = `${d}/${m}/${y}`;
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, dmy);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    done.push(`${el.name || el.id}: ${v} -> ${dmy}`);
                });
                return done;
            }""")
            if fixed:
                logger.info(f"  Preflight fixed name case on tab {tab_num}: {fixed}")
            await asyncio.sleep(0.3)
            errs = await self._collect_errors(page)
            if errs:
                logger.warning(f"  Preflight validation still present tab {tab_num}: {errs[:6]}")
        except Exception as e:
            logger.warning(f"  Preflight save failed: {e}")

    async def _fill_default_required(self, page: Page, data: dict):
        """Select default No/0 for empty required radio groups and fill empty required selects/texts."""
        try:
            filled = await page.evaluate("""() => {
                const done = [];
                // radios: pick value "0" (No) if group empty
                const groups = {};
                document.querySelectorAll('input[type="radio"][required], input[type="radio"]').forEach(r => {
                    if (!r.name) return;
                    groups[r.name] = groups[r.name] || [];
                    groups[r.name].push(r);
                });
                Object.entries(groups).forEach(([name, radios]) => {
                    const any = radios.some(r => r.checked);
                    if (any) return;
                    // only default if marked required or known yes/no style
                    const req = radios.some(r => r.required);
                    if (!req) return;
                    const target = radios.find(r => r.value === '0') || radios.find(r => r.value === 'No') || radios[0];
                    if (target) {
                        target.checked = true;
                        target.dispatchEvent(new Event('change', {bubbles: true}));
                        target.dispatchEvent(new Event('click', {bubbles: true}));
                        done.push(name + '->' + target.value);
                    }
                });
                // empty required selects/texts with data-* not available; mark only
                document.querySelectorAll('select[required]').forEach(s => {
                    if (!s.value) done.push('empty-select:' + (s.name || s.id));
                });
                document.querySelectorAll('input[required], textarea[required]').forEach(el => {
                    if (el.type === 'radio' || el.type === 'checkbox') return;
                    if (!String(el.value || '').trim()) done.push('empty-input:' + (el.name || el.id));
                });
                return done;
            }""")
            if filled:
                logger.info(f"  Default/repair scan: {filled}")
        except Exception as e:
            logger.warning(f"  Default required fill failed: {e}")

        # digital device type if device=yes but type empty
        try:
            sel = page.locator('select[name="digital_device_type[]"]').first
            if await sel.count() > 0:
                val = await sel.input_value()
                if not val:
                    await sel.select_option(value="1", timeout=2000)
                    logger.info("  Set digital_device_type[] -> 1")
        except Exception:
            pass

    async def _repair_address_selects(self, page: Page, data: dict):
        """Re-select required address fields if empty after cascade/same-as."""
        checks = [
            ("address_type", "Address Type", "address_type"),
            ("sector_id", "Sector", "sector_id"),
            ("sub_sector_id", "Sub Sector", "sub_sector_id"),
            ("present_address_type", "Address Type", "present_address_type"),
            ("present_sector_id", "Sector", "present_sector_id"),
            ("present_sub_sector_id", "Sub Sector", "present_sub_sector_id"),
            ("city_id", "City", "city_id"),
            ("birth_province_id", "Province of Birth", "birth_province_id"),
            ("birth_district_id", "District of Birth", "birth_district_id"),
            ("domicile_province_id", "Student Domicile — Province", "domicile_province_id"),
            ("domicile_district_id", "Student Domicile — District", "domicile_district_id"),
            ("nationality", "Nationality", "nationality"),
        ]
        for name, label, source in checks:
            try:
                sel = page.locator(f'select[name="{name}"]').first
                if await sel.count() == 0:
                    continue
                val = await sel.input_value()
                if val:
                    continue
                value = data.get(source)
                if not value and source == "present_sub_sector_id":
                    value = data.get("sub_sector_id")
                if not value:
                    # cascade empty: pick first real option
                    try:
                        opts = await sel.locator("option").all_text_contents()
                        real = [o for o in opts if o and not o.lower().startswith("select")]
                        if real:
                            logger.info(f"  Repair empty select {name} -> first option {real[0]!r}")
                            await sel.select_option(label=real[0], timeout=2000)
                    except Exception as e:
                        logger.warning(f"  Repair first-option {name} failed: {e}")
                    continue
                logger.info(f"  Repair empty select {name} -> {value}")
                await self._fill_dropdown(page, label, str(value), [], name)
            except Exception as e:
                logger.warning(f"  Repair {name} failed: {e}")

        # Text fields that may be cleared
        for name, source in (("house", "house"), ("street", "street"),
                             ("present_house", "present_house"), ("present_street", "present_street")):
            try:
                inp = page.locator(f'[name="{name}"]').first
                if await inp.count() == 0:
                    continue
                val = await inp.input_value()
                if val:
                    continue
                value = data.get(source)
                if not value:
                    continue
                logger.info(f"  Repair empty input {name} -> {value}")
                await self._fill_text(page, name, str(value), name)
            except Exception as e:
                logger.warning(f"  Repair {name} failed: {e}")

    async def submit_form(self, page: Page, student_data: dict | None = None) -> bool:
        """Submit the completed form on the final tab.

        Portal flow: #saveNextBtn ("Save & Next") advances/saves; on the last
        step #finishBtn ("Finish") may become visible. A Confirm dialog may appear.
        Success is a visible H5 "Form Submitted Successfully!".
        """
        logger.info("Submitting form...")
        self._attach_save_listeners(page)

        # Re-fill only if cascade/switch may have cleared fields (skip when fill just ran)
        if student_data and not getattr(self, "_just_filled", False):
            try:
                for i, (tab_name, tab_id) in enumerate(TAB_IDS, 1):
                    tab = page.locator(f"#{tab_id}").first
                    if await tab.count() > 0 and await tab.is_visible():
                        await tab.click(timeout=5000)
                        await asyncio.sleep(0.8)
                    await self._fill_tab_fields(page, i, student_data)
                await self._fill_default_required(page, student_data)
            except Exception as e:
                logger.warning(f"Re-fill before submit failed: {e}")
        elif student_data:
            # Light repair: defaults for empty required radios/selects only
            try:
                await self._fill_default_required(page, student_data)
            except Exception as e:
                logger.warning(f"Default-required repair failed: {e}")

        await self._preflight_save(page, 7)

        # If create-mode personal save already 422'd, switch to edit before finishing
        if student_data and await self._recover_duplicate(page, student_data):
            try:
                for i, (tab_name, tab_id) in enumerate(TAB_IDS, 1):
                    tab = page.locator(f"#{tab_id}").first
                    if await tab.count() > 0:
                        await tab.click(timeout=5000)
                        await asyncio.sleep(0.5)
                    await self._fill_tab_fields(page, i, student_data)
                await self._fill_default_required(page, student_data)
                await self._preflight_save(page, 7)
            except Exception as e:
                logger.warning(f"Re-fill after edit switch failed: {e}")

        # Ensure we are on Digital Access (tab 7)
        try:
            tab = page.locator("#tab-nav-digital").first
            if await tab.count() > 0 and await tab.is_visible():
                await tab.click(timeout=5000)
                await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Could not click tab 7: {e}")

        # Click Save & Next on final tab if visible (saves tab 7 data)
        try:
            save_btn = page.locator("#saveNextBtn").first
            if await save_btn.count() > 0 and await save_btn.is_visible():
                await save_btn.click(timeout=5000)
                await asyncio.sleep(2)
                await self._handle_confirm(page)
                logger.info("Clicked Save & Next on final tab")
        except Exception as e:
            logger.warning(f"Final Save & Next failed: {e}")

        # Portal never POSTs on Next — always force the edit update before Finish
        try:
            if await self._force_save(page):
                logger.info("Force-save before Finish: OK")
            else:
                logger.warning("Force-save before Finish: failed")
        except Exception as e:
            logger.warning(f"Force-save before Finish error: {e}")

        # Finish button (may become visible after last save)
        try:
            finish = page.locator("#finishBtn").first
            if await finish.count() > 0 and await finish.is_visible():
                await finish.click(timeout=5000)
                await asyncio.sleep(2)
                await self._handle_confirm(page)
                logger.info("Clicked Finish")
        except Exception as e:
            logger.warning(f"Finish click failed: {e}")

        # Wait for success heading (visible) or navigation away from create
        success = await self._wait_for_success(page, timeout=15000)

        # Collect validation errors if any
        errors = await self._collect_errors(page)
        if errors:
            logger.warning(f"Validation errors: {errors[:8]}")

        if not success:
            diag = await self._diagnose_failure(page)
            if diag:
                logger.warning(f"Submit diagnostics: {diag}")

        await page.screenshot(path="data/logs/submit_result.png", full_page=True)
        if success:
            logger.info("Form submitted successfully")
        else:
            logger.warning("Submit: success indicator not confirmed")
        return success

    async def _diagnose_failure(self, page: Page) -> dict:
        """Collect active tab, empty required fields, dialogs, finish visibility."""
        try:
            diag = await page.evaluate("""() => {
                const active = document.querySelector('.nav-link.active, .nav-item .active, [role="tab"].active');
                const activeId = active ? (active.id || active.textContent.trim().slice(0,40)) : null;
                const emptyReq = [];
                const radioGroups = {};
                document.querySelectorAll('input, select, textarea').forEach(el => {
                    const name = el.name || el.id;
                    if (!name) return;
                    if (el.type === 'radio') {
                        radioGroups[name] = radioGroups[name] || false;
                        if (el.checked) radioGroups[name] = true;
                    } else if (el.type === 'checkbox') {
                        if (el.required && !el.checked) {
                            emptyReq.push(name + ' [checkbox required]');
                        }
                    } else if (el.required && !String(el.value || '').trim()) {
                        emptyReq.push(name + ' [required empty]');
                    }
                });
                Object.entries(radioGroups).forEach(([name, checked]) => {
                    const el = document.querySelector(`input[name="${name}"]`);
                    if (el && el.required && !checked) emptyReq.push(name + ' [radio required]');
                });
                const errs = Array.from(document.querySelectorAll(
                    '.is-invalid, .invalid-feedback, .invalid-tooltip, .text-danger, .alert, .toast, .error, .error-message, [class*="error"]'
                )).map(e => (e.innerText || '').trim()).filter(t => t && t.length < 300).slice(0, 20);
                const finish = document.querySelector('#finishBtn');
                const save = document.querySelector('#saveNextBtn');
                return {
                    activeTab: activeId,
                    url: location.pathname,
                    emptyRequired: emptyReq.slice(0, 40),
                    errorTexts: errs,
                    finishVisible: finish ? !finish.classList.contains('d-none') && finish.offsetParent !== null : false,
                    saveVisible: save ? !save.classList.contains('d-none') && save.offsetParent !== null : false,
                    hafizChecked: (() => {
                        const yes = document.querySelector('input[name="is_hafiz"][value="1"]');
                        const no = document.querySelector('input[name="is_hafiz"][value="0"]');
                        return {yes: !!(yes && yes.checked), no: !!(no && no.checked)};
                    })(),
                };
            }""")
            if self._dialog_messages:
                diag["dialogs"] = self._dialog_messages[-5:]
            return diag
        except Exception as e:
            return {"error": str(e)}

    async def _handle_confirm(self, page: Page):
        try:
            confirm = page.locator(
                "button:has-text('CONFIRM'), button:has-text('Confirm'), "
                "button:has-text('OK'), button:has-text('Yes')"
            ).first
            if await confirm.count() > 0 and await confirm.is_visible():
                await confirm.click(timeout=3000)
                await asyncio.sleep(1)
                logger.info("Handled confirm dialog button")
        except Exception:
            pass

    async def _wait_for_success(self, page: Page, timeout: int = 15000) -> bool:
        """True when 'Form Submitted Successfully!' is visible or URL leaves /create."""
        deadline = asyncio.get_event_loop().time() + timeout / 1000
        while asyncio.get_event_loop().time() < deadline:
            try:
                if "/students/create" not in page.url and "femis.fde.gov.pk" in page.url:
                    # navigated away from create (e.g. students list)
                    body = await page.content()
                    if "successfully" in body.lower() or "/students" in page.url:
                        return True

                heading = page.locator("h1,h2,h3,h4,h5,h6").filter(
                    has_text=re.compile(r"Form Submitted Successfully", re.I)
                ).first
                if await heading.count() > 0:
                    # must be actually visible (heading exists hidden in DOM by default)
                    if await heading.is_visible():
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    def _attach_save_listeners(self, page: Page):
        """Log XHR/fetch (and any non-GET) so failed saves are visible."""
        self._last_api: list[dict] = []

        async def on_response(resp):
            try:
                req = resp.request
                method = (req.method if req else "GET").upper()
                url = resp.url
                interesting = any(
                    k in url
                    for k in ("/api/", "/students", "/save", "/store", "/step", "/form", "/update")
                )
                # Always keep POST/PUT/PATCH — save may not match keyword filter
                if method == "GET" and not interesting:
                    return
                if method == "OPTIONS" or method == "HEAD":
                    return
                body = ""
                try:
                    body = (await resp.text())[:800]
                except Exception:
                    try:
                        body = (await resp.body())[:800].decode("utf-8", errors="replace")
                    except Exception:
                        pass
                req_body = ""
                try:
                    if req:
                        req_body = req.post_data or ""
                except Exception:
                    pass
                entry = {
                    "status": resp.status,
                    "url": url,
                    "method": method,
                    "body": body,
                    "req": req_body,
                }
                self._last_api.append(entry)
                if method != "GET" or resp.status >= 400:
                    logger.info(f"  NET {method} {resp.status} {url}")
                if resp.status >= 400 or "went wrong" in body.lower() or "error" in body.lower():
                    logger.warning(f"  API {resp.status} {url} :: {body[:400]}")
                    if req_body:
                        logger.warning(f"  REQ body ({len(req_body)} bytes) :: {req_body[:600]}")
                    try:
                        dump = Path("data/logs/api_errors.log")
                        with dump.open("a", encoding="utf-8") as f:
                            f.write(f"\n=== {resp.status} {url} ===\n")
                            f.write(f"CONTENT-TYPE: {resp.headers.get('content-type', '')}\n")
                            f.write(f"REQ ({len(req_body)} bytes):\n{req_body}\n")
                            f.write(f"RESP:\n{body}\n")
                    except Exception:
                        pass
            except Exception:
                pass

        page.on("response", on_response)

    async def _collect_errors(self, page: Page) -> list[str]:
        try:
            errs = await page.evaluate("""() => {
                const els = document.querySelectorAll(
                    '.is-invalid, .invalid-feedback.show, .text-danger, .alert-danger, .toast, .swal2-popup, .toastr-error, [class*="error"]'
                );
                return Array.from(els)
                    .map(e => (e.innerText || e.textContent || '').trim())
                    .filter(t => t && t !== '*' && t.length < 400)
                    .slice(0, 20);
            }""")
            return errs
        except Exception:
            return []

    async def _capture_ui_error(self, page: Page) -> str:
        """Read visible toast/alert/dialog text after a save attempt."""
        try:
            msg = await page.evaluate("""() => {
                const sels = [
                    '.toast-body', '.toast', '.alert', '.swal2-html-container',
                    '.toastr-message', '[role="alert"]', '.modal-body',
                    '.invalid-feedback.show', '.text-danger',
                ];
                const out = [];
                for (const s of sels) {
                    document.querySelectorAll(s).forEach(el => {
                        const t = (el.innerText || '').trim();
                        if (t && t.length < 400) out.push(t);
                    });
                }
                return out.join(' | ');
            }""")
            if msg:
                logger.warning(f"  UI error: {msg[:300]}")
            return msg
        except Exception:
            return ""

    async def _fill_tab_fields(self, page: Page, tab_number: int, data: dict):
        tab_key = f"tab_{tab_number}_"
        tab_data = None
        for key in self.field_map:
            if key.startswith(tab_key):
                tab_data = self.field_map[key]
                break

        if not tab_data:
            return

        for section_name, section_fields in tab_data.items():
            if not isinstance(section_fields, dict) or "status" in section_fields:
                continue
            if "type" in section_fields:
                await self._fill_field(page, section_name, section_fields, data)
            else:
                # Fill city first in permanent section so same-as checkbox enables,
                # then address fields, then same-as last (portal may require order).
                if tab_number == 1 and section_name == "address_permanent":
                    order = [
                        "city",
                        "address_type",
                        "sector",
                        "sub_sector",
                        "village",
                        "housing_society",
                        "house_number",
                        "street_number",
                        "same_as_temporary",
                    ]
                    seen = set()
                    for field_name in order:
                        config = section_fields.get(field_name)
                        if isinstance(config, dict) and "type" in config:
                            await self._fill_field(page, field_name, config, data)
                            seen.add(field_name)
                    for field_name, config in section_fields.items():
                        if field_name in seen:
                            continue
                        if isinstance(config, dict) and "type" in config:
                            await self._fill_field(page, field_name, config, data)
                    continue
                for field_name, config in section_fields.items():
                    if isinstance(config, dict) and "type" in config:
                        await self._fill_field(page, field_name, config, data)

        if tab_number == 1:
            await self._repair_address_selects(page, data)

    def _portal_name(self, config: dict) -> str:
        source = config.get("source_field") or ""
        return PORTAL_NAME_ALIASES.get(source, source)

    async def _fill_field(self, page: Page, field_name: str, config: dict, data: dict):
        source_field = config.get("source_field", field_name)
        value = data.get(source_field)

        # Portal defaults: only ask conditional fields when the parent flag is set.
        def _truthy(v) -> bool:
            return str(v if v is not None else "").strip().lower() in ("1", "yes", "true", "y")

        if source_field == "orphan_type" and not _truthy(data.get("is_orphan")):
            return
        if source_field == "glass_prescription" and not _truthy(data.get("uses_glasses")):
            return
        # Portal default: bus_route set => Institution Bus when transport blank
        if source_field == "transport_facility" and value in (None, ""):
            if data.get("bus_route"):
                value = "Institution Bus"

        # Guardian block: portal still requires Guardian Name for non-orphans;
        # default from father when DB guardian is blank.
        if source_field.startswith("guardian_") and value in (None, "") and not _truthy(data.get("is_orphan")):
            father_map = {
                "guardian_name": "father_name",
                "guardian_cnic": "father_cnic",
                "guardian_contact": "father_contact",
                "guardian_relation": None,  # set below
            }
            if source_field == "guardian_relation":
                value = "Father"
            else:
                src = father_map.get(source_field)
                if src:
                    value = data.get(src)

        if value is None or str(value).strip() == "":
            if config.get("required"):
                # Device Type is only needed when the student has a device
                if source_field == "digital_device_type" and str(data.get("digital_device_at_home") or "0").strip() in ("0", "No", "no", ""):
                    return
                logger.warning(f"  Missing required: {config.get('label', field_name)}")
            return

        value = str(value).strip()
        field_type = config.get("type", "text")
        label = config.get("label", field_name)
        validation = config.get("validation")
        portal_name = self._portal_name(config)

        # Normalize junk auto-learn labels back to real portal labels
        if label in ("is_orphan", "is_father_alive", "is_mother_alive", "transport_facility",
                     "school_meal_program_availing", "basic_vaccination_completed"):
            label = {
                "is_orphan": "Is Orphan Child",
                "is_father_alive": "Is Father Alive",
                "is_mother_alive": "Is Mother Alive",
                "transport_facility": "Transport Facility",
                "school_meal_program_availing": "Meal Program",
                "basic_vaccination_completed": "Basic Vaccination Completed",
            }[label]
        if field_name in ("class", "class_admitted_in") and value.isdigit():
            value = f"Class {value}"

        # Portal requires capital alphabets on personal-name fields
        if source_field in CAPITAL_NAME_SOURCES:
            value = re.sub(r"[^A-Za-z .'-]", "", value).upper()

        if validation and value:
            if validation == "cnic":
                value = format_cnic(value)
            elif validation == "mobile_pakistani":
                value = format_mobile(value)

        # Never fill a control that is hidden on another tab (Illegal invocation / wrong field)
        try:
            if portal_name:
                vis = await page.evaluate(
                    """(name) => {
                        const el = document.querySelector(`[name="${CSS.escape(name)}"]`);
                        if (!el) return true;
                        const st = window.getComputedStyle(el);
                        if (st.display === 'none' || st.visibility === 'hidden') return false;
                        if (el.closest('[hidden], .d-none, .tab-pane:not(.active):not(.show)')) return false;
                        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                    }""",
                    portal_name,
                )
                if vis is False:
                    if config.get("required"):
                        logger.warning(f"  Skip (hidden on this tab): {label}")
                    return
        except Exception:
            pass

        try:
            if field_type == "text":
                await self._fill_text(page, label, value, portal_name)
            elif field_type == "dropdown":
                await self._fill_dropdown(page, label, value, config.get("options", []), portal_name)
            elif field_type == "radio":
                await self._fill_radio(page, label, value, portal_name)
            elif field_type == "date":
                await self._fill_date(page, label, value, portal_name)
            elif field_type == "checkbox":
                await self._fill_checkbox(page, label, value, portal_name)
            # Verify control actually took the value when possible
            if field_type in ("text", "dropdown", "date"):
                await self._verify_filled(page, label, portal_name, value)
            elif field_type == "radio" and portal_name:
                # Alias may differ from DOM name (e.g. transport_facility vs transport)
                if not await self._radio_checked(page, portal_name) and not await self._radio_checked(page, source_field):
                    raise RuntimeError(f"Radio not checked after fill: {portal_name}={value}")
            logger.info(f"  OK: {label} = {value[:50]}")
        except Exception as e:
            logger.error(f"  FAIL: {label}: {e}")

    async def _verify_filled(self, page: Page, label: str, portal_name: str, expected: str):
        """Raise if the target control is still empty after a fill attempt."""
        try:
            if portal_name:
                loc = page.locator(f'[name="{portal_name}"]').first
                if await loc.count() > 0:
                    tag = await loc.evaluate("el => el.tagName")
                    if tag == "SELECT":
                        cur = await loc.evaluate("el => el.value")
                        if not str(cur or "").strip():
                            raise RuntimeError(f"Select still empty after fill: {portal_name}")
                        return
                    cur = await loc.input_value()
                    if not str(cur or "").strip() and str(expected or "").strip():
                        raise RuntimeError(f"Input still empty after fill: {portal_name}")
                    return
            # Label-based fallback
            container = await self._find_label(page, label)
            if container and await container.count() > 0:
                for sel_css in ("select", "input", "textarea"):
                    el = container.locator("..").locator(sel_css).first
                    if await el.count() > 0:
                        tag = await el.evaluate("el => el.tagName")
                        if tag == "SELECT":
                            cur = await el.evaluate("el => el.value")
                        else:
                            try:
                                cur = await el.input_value()
                            except Exception:
                                cur = ""
                        if not str(cur or "").strip() and str(expected or "").strip():
                            raise RuntimeError(f"Control still empty after fill: {label}")
                        return
        except RuntimeError:
            raise
        except Exception:
            # Verification is best-effort; do not mask a successful fill
            pass

    async def _fill_text(self, page: Page, label: str, value: str, portal_name: str = ""):
        # 1. By portal name attribute (most reliable)
        if portal_name:
            try:
                inp = page.locator(f'[name="{portal_name}"]').first
                if await inp.count() > 0:
                    await inp.scroll_into_view_if_needed(timeout=2000)
                    await inp.click(timeout=2000)
                    await inp.fill("")
                    await inp.fill(value, timeout=3000)
                    return
            except Exception:
                pass

        # 2. By label
        try:
            container = await self._find_label(page, label)
            if container and await container.count() > 0:
                inp = container.locator("..").locator(
                    "input[type='text'], input[type='number'], input[type='email'], input[type='tel'], input:not([type])"
                ).first
                if await inp.count() == 0:
                    inp = container.locator("..").locator(
                        "textarea, input[type='text'], input[type='number'], input[type='email'], input[type='tel'], input:not([type])"
                    ).first
                if await inp.count() == 0:
                    inp = container.locator("..").locator("input, textarea").first
                if await inp.count() > 0:
                    await inp.scroll_into_view_if_needed(timeout=2000)
                    await inp.click(timeout=2000)
                    await inp.fill("")
                    await inp.fill(value, timeout=3000)
                    return
        except Exception:
            pass

        # 3. JS fallback by name (input or textarea)
        if portal_name:
            await page.evaluate(
                """(args) => {
                    const [name, val] = args;
                    const el = document.querySelector(`[name="${name}"]`);
                    if (el) {
                        const proto = el.tagName === 'TEXTAREA'
                            ? window.HTMLTextAreaElement.prototype
                            : window.HTMLInputElement.prototype;
                        const nativeSet = Object.getOwnPropertyDescriptor(proto, 'value').set;
                        nativeSet.call(el, val);
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        if (window.jQuery) { jQuery(el).val(val).trigger('change'); }
                    }
                }""",
                [portal_name, value],
            )
            return

        raise RuntimeError(f"No input found for label={label!r} name={portal_name!r}")

    async def _fill_dropdown(self, page: Page, label: str, value: str, options: list, portal_name: str = ""):
        sel = None
        if portal_name:
            try:
                cand = page.locator(f'select[name="{portal_name}"]').first
                if await cand.count() > 0:
                    sel = cand
            except Exception:
                pass

        if sel is None:
            try:
                container = await self._find_label(page, label)
                if container and await container.count() > 0:
                    sel = container.locator("..").locator("select").first
                    if await sel.count() == 0:
                        sel = None
            except Exception:
                sel = None

        if sel is None:
            try:
                sel = page.locator("label").filter(has_text=label).locator("..").locator("select").first
                if await sel.count() == 0:
                    sel = None
            except Exception:
                sel = None

        if sel is None:
            # Portal sometimes exposes Shift (and similar) as radios, not selects
            try:
                await self._fill_radio(page, label, value, portal_name)
                return
            except Exception:
                pass
            raise RuntimeError(f"No select found for label={label!r} name={portal_name!r}")

        try:
            await sel.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass

        # Cascade selects (Sub Sector, Section, District) load options after parent change
        cascade_names = {
            "sub_sector_id", "present_sub_sector_id", "section_id",
            "birth_district_id", "father_domicile_district_id", "class_group_id",
            "domicile_district_id",
        }
        if portal_name in cascade_names:
            for _ in range(24):
                try:
                    n = await sel.locator("option").count()
                    if n > 1:
                        break
                except Exception:
                    break
                await asyncio.sleep(0.25)

        # 1. Exact label match
        try:
            await sel.select_option(label=value, timeout=3000)
            return
        except Exception:
            pass

        # 2. Value attribute match
        try:
            await sel.select_option(value=value, timeout=2000)
            return
        except Exception:
            pass

        # 3. Truncated label
        try:
            await sel.select_option(label=value[:50], timeout=2000)
            return
        except Exception:
            pass

        # 4. Fuzzy match
        matched = self._fuzzy_match(value, options)
        if matched:
            try:
                await sel.select_option(label=matched, timeout=2000)
                return
            except Exception:
                pass

        # 4b. Fuzzy match against live DOM options
        try:
            dom_opts = await sel.locator("option").all_text_contents()
            cleaned = [o.strip() for o in dom_opts if o and o.strip() and not o.strip().lower().startswith("select")]
            dom_matched = self._fuzzy_match(value, cleaned)
            if dom_matched:
                await sel.select_option(label=dom_matched, timeout=2000)
                return
        except Exception:
            pass

        # 5. JS fallback
        name = portal_name
        if not name:
            try:
                name = await sel.get_attribute("name") if await sel.count() > 0 else None
            except Exception:
                name = None
        if name:
            try:
                await page.evaluate(
                    """(args) => {
                        const [name, val] = args;
                        const el = document.querySelector('select[name="' + name + '"]');
                        if (!el) return;
                        for (const opt of el.options) {
                            const t = (opt.text || '').trim();
                            if (opt.value === val || (t && t.includes(val)) || (val && val.includes(t))) {
                                el.value = opt.value;
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                const jq = window.jQuery;
                                if (typeof jq === 'function') {
                                    try { jq(el).trigger('change'); } catch (e) {}
                                }
                                break;
                            }
                        }
                    }""",
                    [name, matched or value],
                )
                return
            except Exception:
                pass

        logger.warning(f"    No match for '{value}' in '{label}'")

    async def _fill_radio(self, page: Page, label: str, value: str, portal_name: str = ""):
        value_lower = str(value or "").strip().lower()
        # Portal encodes Yes/No as 1/0 (and sometimes Yes/No literals).
        if value_lower in ("yes", "true", "1"):
            candidates = ["1", "Yes", "yes", "true", "True"]
        elif value_lower in ("no", "false", "0"):
            candidates = ["0", "No", "no", "false", "False"]
        else:
            candidates = [str(value), value_lower]
        if str(value) not in candidates:
            candidates.insert(0, str(value))

        # 0. JS scan: find radio group whose nearby label/legend contains the
        # field label, then pick option by value or option text (portal often
        # uses value labels "1"/"0" instead of Yes/No).
        if label or portal_name:
            try:
                hit = await page.evaluate(
                    """(args) => {
                        const [label, name, cands, want] = args;
                        const norm = s => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                        const wantL = norm(want);
                        const candSet = new Set((cands || []).map(c => norm(c)));
                        candSet.add(wantL);
                        if (wantL === '1' || wantL === 'yes') ['1', 'yes', 'true'].forEach(x => candSet.add(x));
                        if (wantL === '0' || wantL === 'no') ['0', 'no', 'false'].forEach(x => candSet.add(x));
                        const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
                        if (!radios.length) return null;
                        const groupText = (el) => {
                            const box = el.closest('.form-group, .mb-3, fieldset, .form-check, .col, .row, label')
                                || el.parentElement?.parentElement || el.parentElement || el;
                            return norm(box.innerText || box.textContent || '');
                        };
                        const labelNorm = norm(label);
                        const nameNorm = norm(name);
                        // Prefer exact portal name when given
                        let pool = name
                            ? radios.filter(r => norm(r.name) === nameNorm || norm(r.name) === norm(name) + '[]')
                            : [];
                        if (!pool.length && labelNorm) {
                            pool = radios.filter(r => groupText(r).includes(labelNorm));
                            // Also: field label as sibling/legend near a shared name
                            if (!pool.length) {
                                const els = Array.from(document.querySelectorAll(
                                    'label, legend, .form-label, .control-label'
                                ));
                                const head = els.find(e => norm(e.innerText || e.textContent).includes(labelNorm));
                                if (head) {
                                    const box = head.closest('.form-group, .mb-3, fieldset') || head.parentElement;
                                    if (box) pool = Array.from(box.querySelectorAll('input[type="radio"]'));
                                }
                            }
                        }
                        if (!pool.length) return null;
                        const name0 = pool[0].name;
                        pool = radios.filter(r => r.name === name0);
                        const optMatch = (r) => {
                            const v = norm(r.value);
                            if (candSet.has(v)) return true;
                            const lab = r.labels && r.labels[0]
                                ? norm(r.labels[0].innerText || r.labels[0].textContent)
                                : '';
                            if (candSet.has(lab)) return true;
                            // option text equals want (e.g. "institution bus")
                            if (lab && (lab === wantL || wantL.includes(lab) || lab.includes(wantL))) return true;
                            return false;
                        };
                        const target = pool.find(optMatch) || null;
                        if (!target) return null;
                        const clickIt = () => {
                            if (typeof target.click === 'function') target.click();
                            else { target.checked = true; }
                            target.checked = true;
                            target.dispatchEvent(new Event('input', { bubbles: true }));
                            target.dispatchEvent(new Event('change', { bubbles: true }));
                            target.dispatchEvent(new Event('click', { bubbles: true }));
                            if (window.jQuery) { try { jQuery(target).trigger('click').trigger('change'); } catch (e) {} }
                        };
                        clickIt();
                        if (target.labels && target.labels[0]) {
                            try { target.labels[0].click(); } catch (e) {}
                        }
                        return {
                            name: target.name,
                            value: target.value,
                            checked: !!target.checked,
                            anyChecked: pool.some(r => r.checked),
                        };
                    }""",
                    [label or "", portal_name or "", candidates, str(value)],
                )
                if hit and (hit.get("checked") or hit.get("anyChecked")):
                    logger.info(
                        f"  Radio JS OK: name={hit.get('name')!r} value={hit.get('value')!r} "
                        f"for {label!r}={value!r}"
                    )
                    if portal_name and await self._radio_checked(page, portal_name):
                        return
                    if hit.get("name") and await self._radio_checked(page, hit["name"]):
                        return
                    # Group name differs from yaml portal_name — still accept if checked
                    if hit.get("checked"):
                        return
            except Exception as e:
                logger.debug(f"Radio JS scan failed for {label!r}: {e}")

        # 1. By name + any candidate value
        if portal_name:
            for cand in candidates:
                try:
                    radio = page.locator(f'input[type="radio"][name="{portal_name}"][value="{cand}"]').first
                    if await radio.count() > 0:
                        await self._click_radio(page, radio)
                        if await self._radio_checked(page, portal_name):
                            return
                except Exception:
                    pass

        # 2. By label container
        try:
            container = await self._find_label(page, label)
            if container and await container.count() > 0:
                for cand in candidates:
                    radio_by_val = container.locator("..").locator(f"input[type='radio'][value='{cand}']")
                    if await radio_by_val.count() > 0:
                        await self._click_radio(page, radio_by_val.first)
                        pname = await radio_by_val.first.get_attribute("name")
                        if pname and await self._radio_checked(page, pname):
                            return
                radio_by_label = container.locator("..").locator(f"label:has-text('{value}')")
                if await radio_by_label.count() > 0:
                    await radio_by_label.click(force=True, timeout=2000)
                    return
        except Exception:
            pass

        # 3. By visible group label
        try:
            group = page.locator(f'.form-group:has(label:has-text("{label}")), .mb-3:has(label:has-text("{label}")), fieldset:has(legend:has-text("{label}"))').first
            if await group.count() > 0:
                for cand in candidates:
                    opts = group.locator(f"input[type='radio'][value='{cand}']")
                    if await opts.count() > 0:
                        await opts.first.click(force=True, timeout=2000)
                        pname = await opts.first.get_attribute("name")
                        if pname and await self._radio_checked(page, pname):
                            return
                    lab = group.locator(f"label:has-text('{cand}')")
                    if await lab.count() > 0:
                        await lab.first.click(force=True, timeout=2000)
                        return
        except Exception:
            pass

        # 4. By name only: match option label text to Yes/No-style value
        if portal_name:
            try:
                radios = page.locator(f'input[type="radio"][name="{portal_name}"]')
                if await radios.count() > 0:
                    labels = await radios.evaluate_all(
                        "els => els.map(e => ((e.labels && e.labels[0]) ? e.labels[0].innerText : e.value || '').trim())"
                    )
                    want_words = {value_lower}
                    if value_lower in ("1", "yes", "true"):
                        want_words |= {"yes", "true", "1"}
                    if value_lower in ("0", "no", "false"):
                        want_words |= {"no", "false", "0"}
                    target = None
                    for i, lab in enumerate(labels):
                        low = (lab or "").lower()
                        if any(w and (w == low or w in low or low in w) for w in want_words):
                            target = radios.nth(i)
                            break
                    if target is None:
                        for cand in candidates:
                            t = radios.locator(f'[value="{cand}"]')
                            if await t.count() > 0:
                                target = t
                                break
                    if target is not None and await target.count() > 0:
                        await self._click_radio(page, target.first if hasattr(target, "first") else target)
                        if await self._radio_checked(page, portal_name):
                            return
            except Exception:
                pass

        # 5. Label-text search across page (Is Father Alive / Basic Vaccination / ...)
        try:
            for cand in candidates + [label]:
                if not cand:
                    continue
                lab = page.locator(f"label:has-text('{cand}')").first
                if await lab.count() > 0:
                    # Prefer a label inside a group that also mentions our field label
                    scoped = page.locator(
                        f'.form-group:has(label:has-text("{label}")) label:has-text("{cand}"), '
                        f'.mb-3:has(label:has-text("{label}")) label:has-text("{cand}"), '
                        f'fieldset:has(legend:has-text("{label}")) label:has-text("{cand}")'
                    ).first
                    click = scoped if await scoped.count() > 0 else lab
                    await click.click(force=True, timeout=2000)
                    if portal_name and await self._radio_checked(page, portal_name):
                        return
                    # If name unknown, assume click on the right group succeeded when label matched field label context
                    if not portal_name:
                        return
        except Exception:
            pass

        raise RuntimeError(f"No radio found for label={label!r} value={value!r} name={portal_name!r}")

    async def _radio_checked(self, page: Page, portal_name: str) -> bool:
        try:
            return await page.evaluate(
                """(name) => Array.from(document.querySelectorAll(`input[type="radio"][name="${name}"]`))
                    .some(r => r && r.checked)""",
                portal_name,
            )
        except Exception:
            return False

    async def _click_radio(self, page: Page, radio):
        try:
            await radio.click(force=True, timeout=2000)
        except Exception:
            name = await radio.get_attribute("name")
            rid = await radio.get_attribute("id")
            val = await radio.get_attribute("value")
            if name:
                await page.evaluate(
                    """(args) => {
                        const [name, val, id] = args;
                        const label = id ? document.querySelector(`label[for="${id}"]`) : null;
                        if (label) { label.click(); return; }
                        const radio = document.querySelector(`input[type='radio'][name='${name}'][value='${val}']`);
                        if (radio) {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('click', {bubbles: true}));
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            radio.dispatchEvent(new Event('input', {bubbles: true}));
                            if (window.jQuery) { jQuery(radio).trigger('click').trigger('change'); }
                        }
                    }""",
                    [name, val or "", rid or ""],
                )

    @staticmethod
    def _normalize_date(value: str) -> str:
        """Normalize any common date format to YYYY-MM-DD for HTML date inputs.

        Day-first is authoritative (web form / users enter dd.mm.yyyy or dd/mm/yyyy).
        Month-first formats are only tried when unambiguous (first part > 12).
        """
        value = (value or "").strip().replace(",", "")
        if not value:
            return value
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value
        # Prefer day-first explicitly (dd/mm, dd-mm, dd.mm)
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        # Unambiguous US-style only when day part cannot be a month (e.g. 13/02/2010)
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", value)
        if m:
            a, b, y = m.groups()
            if len(y) == 2:
                y = "20" + y
            a_i, b_i = int(a), int(b)
            if a_i > 12 and b_i <= 12:
                # clearly day-first already handled; fallback
                return f"{y}-{b_i:02d}-{a_i:02d}"
            if b_i > 12 and a_i <= 12:
                # clearly month-first (US)
                return f"{y}-{a_i:02d}-{b_i:02d}"
            # Ambiguous: treat as day-first (matches portal users / PK locale)
            return f"{y}-{b_i:02d}-{a_i:02d}"
        return value

    @staticmethod
    def _iso_to_portal(iso: str) -> str:
        """Portal POST rejects ISO; wants DD/MM/YYYY (confirmed via bisect).

        Display in portal datepicker may still show mm.dd.yyyy — same instant.
        """
        if re.match(r"^\d{4}-\d{2}-\d{2}$", iso or ""):
            y, m, d = iso.split("-")
            return f"{d}/{m}/{y}"
        return iso

    async def _fill_date(self, page: Page, label: str, value: str, portal_name: str = ""):
        value = self._normalize_date(value)
        portal_val = self._iso_to_portal(value)
        name_attr = portal_name or ""
        if not name_attr:
            try:
                container = await self._find_label(page, label)
                if container and await container.count() > 0:
                    inp = container.locator("..").locator("input").first
                    if await inp.count() > 0:
                        name_attr = await inp.get_attribute("name") or ""
            except Exception:
                pass
        if not name_attr:
            name_attr = "date_of_birth" if "birth" in label.lower() else "date_of_admission"
        await page.evaluate(
            """(args) => {
                const [iso, dmy, name] = args;
                const input = document.querySelector(`input[name="${name}"]`) || document.querySelector('input[type="date"]');
                if (input) {
                    // type=date forces ISO on submit (server 500s on ISO) — switch to text + DD/MM/YYYY
                    if (input.type === 'date') {
                        input.type = 'text';
                    }
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    nativeInputValueSetter.call(input, dmy || iso);
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    if (window.jQuery) { jQuery(input).val(dmy || iso).trigger('change'); }
                }
            }""",
            [value, portal_val, name_attr],
        )

    async def _fill_checkbox(self, page: Page, label: str, value: str, portal_name: str = ""):
        should_check = value.lower() in ("yes", "true", "1", "on")

        cb = None
        if portal_name:
            try:
                cand = page.locator(f'input[type="checkbox"][name="{portal_name}"]').first
                if await cand.count() > 0:
                    cb = cand
            except Exception:
                pass

        if cb is None:
            try:
                container = await self._find_label(page, label)
                if container and await container.count() > 0:
                    cb = container.locator("..").locator("input[type='checkbox']").first
                    if await cb.count() == 0:
                        cb = None
            except Exception:
                cb = None

        if cb is None:
            try:
                cb = page.locator("label").filter(has_text=label).locator("..").locator("input[type='checkbox']").first
                if await cb.count() == 0:
                    cb = None
            except Exception:
                cb = None

        if cb is None:
            logger.warning(f"    No checkbox for '{label}'")
            return

        is_checked = await cb.is_checked()
        if is_checked != should_check:
            await cb.click(force=True)

    async def _find_label(self, page: Page, label: str):
        """Find a label element, handling apostrophes and special characters."""
        loc = page.locator("label").filter(has_text=label).first
        if await loc.count() > 0:
            return loc
        return page.locator("label").filter(has_text=label[:30]).first

    def _fuzzy_match(self, value: str, options: list) -> str | None:
        if not options:
            return None
        vl = value.lower()
        for opt in options:
            if vl == opt.lower():
                return opt
        for opt in options:
            if vl in opt.lower() or opt.lower() in vl:
                return opt
        return None

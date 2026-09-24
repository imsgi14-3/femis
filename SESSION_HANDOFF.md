# Session Handoff — 2026-09-24 (Session 3)

## Completed Work

### Force-save + submit (committed `87c7964`)
- `_force_save` in `src/form_filler.py`: enables all `#studentForm` fields, POSTs `FormData` + `_method=PUT` to `form.action` with `X-XSRF-TOKEN` → `Saved successfully` verified on every tab.
- Called after final tab 7 and before Finish in `submit_form`.
- Earlier `--submit` run SUCCESS for student #6 (Ayat Mubeen) before portal went down.
- Radio verify checks `source_field`; broken `transport` alias removed.
- Dropdown JS jQuery guard fixed ("Illegal invocation").
- Session must use `storage_state=FEMISAuth.storage_state_path()` or captcha reappears.
- Portal list search: name only + digit CNIC compare (CNIC filter broken).

### FEMIS mandatory-field alignment (committed `c99b6e7`)
- Web form + mapping + bot aligned to FEMIS rules:
  - Father qualification/income, mother income (unless Housewife), guardian name/CNIC/relation/WhatsApp/profession/income required.
  - Orphan Type required if Orphan=Yes; Orphan=Yes blocked when both parents alive.
  - Date of Admission `mm/dd/yyyy`; Class Admitted 1–5→1–5, 6–10→6–10.
  - Primary Education Years **not** mandatory.
  - Meal / Transport / Scholarship / Co-curricular required; Transport option = **Institution Bus**.
  - IDP Status + Registered Refugee required if Refugee=Yes.
  - Major/Mental disability, Visually FIT, Wears Glasses, Hearing Difficulty, Listening, Walking, Crutches/Walker required.
  - Glasses Prescription required when Visually FIT=**No**; Hearing Aid if Hearing Difficulty=Yes.
  - Digital Device + Internet Access required; Device Type if Device=Yes.
- Bot `_empty_required_on_tab` glass rule updated to match (visually_fit=No).
- Smoke gate **17/17**.

### This-session fixes (uncommitted)
- Recreated `src/ocr/local_captcha.py` (was deleted by mistake; `auth.py` imports `solve_local`). Stub returns `''` so manual captcha path is used.
- `_probe_pages.py` temp probe created (delete before commit).

## Portal status — BLOCKED
- **femis.fde.gov.pk returns 503 Service Unavailable** (list + create). Server down until ~18:00.
- Last bot run (pre-503 diagnosis): session reused, no captcha; list page had no search input → opened create → tabs missing / form not on page. Root cause = portal 503, not bot logic.

## Git & File Footprint
| Commit | Contents |
|--------|----------|
| `87c7964` (pushed) | force-save, submit, smoke 16/16 |
| `c99b6e7` (pushed) | FEMIS mandatory fields, Institution Bus, smoke 17/17 |
| **dirty** | `src/ocr/local_captcha.py` (new stub), `_probe_pages.py` (temp) |

## Master Roadmap Alignment
**Portal fill + persist + submit path complete (~7 of 8).** Mandatory-field alignment done. Waiting on portal recovery for end-to-end re-verify.

## Next Session Anchor
1. After portal is up (~18:00): delete `_probe_pages.py`, then re-run  
   `Remove-Item data\logs\captcha_code.txt -ErrorAction SilentlyContinue; python test_bot.py --student-id 6 --slow 40 --submit`  
   (manual captcha if session expired).
2. Confirm edit-page persistence + success toast for student #6.
3. Commit `src/ocr/local_captcha.py` stub (or restore real OCR) only if user asks.

## Known Non-Blockers
- Portal down 503 until ~18:00 (2026-09-24).
- DBs not synced (local SQLite vs PythonAnywhere); user works locally.
- Portal save date format `DD/MM/YYYY`; admission field UI wants `mm/dd/yyyy`.
- Manual captcha: write 4 digits to `data/logs/captcha_code.txt` after seeing `captcha_current.png`.

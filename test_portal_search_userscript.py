"""Static regression locks for the FEMIS B-Form Search userscript.

Locks the distribution contract (Tampermonkey metadata), the data path
(same-origin fetch of the portal's DataTables JSON, full columns payload,
page-context only — no GM_* grants, no eval), the matching rules
(digits normalization, TMP handling, uuid record links) and the cache
(sessionStorage + TTL). Live behaviour is covered by _validate_userscript.py
(requires portal session; run manually).

Run: python test_portal_search_userscript.py   (exit 0 = all pass)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SCRIPT = ROOT / "portal-search" / "femis-bform-search.user.js"

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


src = SCRIPT.read_text(encoding="utf-8")

check("userscript file exists", SCRIPT.exists(), str(SCRIPT))
check("@name present", "@name         FEMIS B-Form Search" in src)
check("@match limited to students pages",
      "@match        https://femis.fde.gov.pk/students*" in src)
check("@grant none (page context, own session cookies)",
      "@grant        none" in src)
check("@run-at document-idle", "@run-at       document-idle" in src)
check("@version present (update propagation)",
      bool(re.search(r"//\s*@version\s+\d+\.\d+\.\d+", src)))

check("digits normalization present", "replace(/\\D/g" in src)
check("TMP id search branch", re.search(r"/\^TMP/i\.test", src) is not None)
check("exact-then-partial split", "partial.push" in src and "exact.push" in src)

check("same-origin fetch of portal list",
      "fetch('/students?" in src and "credentials: 'same-origin'" in src)
check("full DataTables columns payload (search reliability)",
      "columns[' + i + '][data]=" in src)
check("auto-pagination for lists over one page",
      "start += data.length" in src and "PAGE_LENGTH" in src)
check("session-expired detection via content-type",
      "indexOf('json') === -1" in src)

check("15-min sessionStorage cache", "sessionStorage" in src and "CACHE_TTL_MS" in src)
check("open/closed state persisted in localStorage (stays closed across URL changes)",
      "localStorage" in src and "OPEN_KEY" in src and "readOpenPref" in src)
check("close persists closed; toggle persists open",
      "writeOpenPref('0')" in src and "writeOpenPref('1')" in src)
check("batch mode", "fbs-batch" in src and "Batch mode" in src)
check("status filter dropdown (Any/Active/Inactive)",
      "fbs-status-filter" in src and "applyStatusFilter" in src and
      "Any status" in src and "Active" in src and "Inactive" in src)
check("status label from badge HTML with is_active fallback",
      "statusLabel" in src and "row.is_active ? 'Active' : 'Inactive'" in src)
check("class filter dropdown (dynamic options with counts)",
      "fbs-class-filter" in src and "populateClassFilter" in src and "applyClassFilter" in src)
check("blank-class students filterable (need to know blanks)",
      "__BLANK__" in src and "Blank (no class)" in src and "classLabel" in src)
check("class column shows dash for blanks", "classLabel(row) || '—'" in src)
check("filters work without a query (show ALL inactive / blank class)",
      "if (!statusVal && !classVal && !nameVal.trim())" in src and
      "No students match the selected filters" in src and
      "students shown" in src and
      "filter-only mode" in src)
check("input prompt only when box AND all filters empty",
      "'Enter a B-Form, TMP ID, or name'" in src)
check("list warmed so class dropdown is ready before first search",
      "function warm()" in src and "warming" in src)
check("record links built from uuid", "'/students/' + row.uuid" in src)
check("edit link from uuid", "'/students/' + row.uuid + '/edit'" in src)
check("per-row status action next to view/edit (portal update-status route)",
      "fbs-status-act" in src and "'/students/update-status/'" in src and
      "function toggleStatus" in src)
check("link direction mirrors current state (inactive on Active, active on Inactive)",
      "statusLabel(row) === 'Inactive' ? 'active' : 'inactive'" in src and
      "linkEl.textContent = makeInactive ? 'active' : 'inactive'" in src)
check("confirm prompt names the target state",
      "window.confirm(" in src and "+ target + '?'" in src)
check("status change updates row, rendered cell, link direction and cache",
      "patchRowInCache" in src and "row.is_active = !makeInactive" in src and
      "cells[6].textContent = target" in src)
check("login redirect detected on status change (no silent fake success)",
      "indexOf('/login')" in src)

check("no eval", "eval(" not in src)
check("no new Function", "new Function" not in src)
check("no GM_* privileged APIs", not re.search(r"\bGM_[a-zA-Z_]+", src))
check("no external network endpoints",
      "http://" not in src.replace("http-equiv", "") and
      not re.search(r"fetch\(['\"]https?://", src))

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)

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
check("batch mode", "fbs-batch" in src and "Batch mode" in src)
check("record links built from uuid", "'/students/' + row.uuid" in src)
check("edit link from uuid", "'/students/' + row.uuid + '/edit'" in src)

check("no eval", "eval(" not in src)
check("no new Function", "new Function" not in src)
check("no GM_* privileged APIs", not re.search(r"\bGM_[a-zA-Z_]+", src))
check("no external network endpoints",
      "http://" not in src.replace("http-equiv", "") and
      not re.search(r"fetch\(['\"]https?://", src))

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)

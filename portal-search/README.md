# FEMIS B-Form Search (browser userscript)

Search **all** students on `femis.fde.gov.pk` by B-Form / Student ID, TMP ID, or
name — the portal's own search box only matches names; this finds everything.

Runs inside Chrome/Edge/Chromebook via Tampermonkey. Uses **your own portal
login** — no credentials are stored or transmitted anywhere. Works on any
laptop: install once per device, then it stays up to date automatically.

## Install (any Chrome / Chromebook, once per device)

1. Install **Tampermonkey** from the Chrome Web Store
   (https://chromewebstore.google.com/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobfkfo).
2. Open:
   https://raw.githubusercontent.com/imsgi14-3/femis/main/portal-search/femis-bform-search.user.js
3. Tampermonkey shows an install page → click **Install**.

That's it. Tampermonkey re-checks that URL periodically, so updates to this
repo reach every device automatically. (No GitHub account needed to install.)

Alternative: Tampermonkey → Create a new script → paste the file contents → Save.

## Use

1. Log into https://femis.fde.gov.pk as usual.
2. Open the Students list (https://femis.fde.gov.pk/students).
3. Click the blue **B-Form Search** button (top-right).
4. Type any of:
   - B-Form number — with or without dashes (`3740245784474` or `37402-4578447-4`)
   - Partial digits (4+ digits) → exact matches first, "contains" matches highlighted below
   - `TMP-2026-…` temporary ID (any case)
   - Student name (4+ letters)
5. Optional name filter narrows results further.
6. Optional **Status** dropdown (Any / Active / Inactive) limits results to
   students with that status — applies to batch mode too.
7. Optional **Class** dropdown — populated from the actual list with counts
   (e.g. "Class 9 (150)") — plus a **Blank (no class)** entry to find
   students not assigned to any class. Also applies to batch mode.
8. **Filters work alone**: leave the search box empty, pick a Status and/or
   Class filter and press Search — the full matching set is listed (e.g. all
   Inactive students, or every blank-class record), no B-Form needed. The
   input prompt only appears when the box *and* all filters are empty.
9. **Batch mode**: paste a list (one B-Form/TMP per line) → all resolved at once.
10. Results show Name, B-Form, TMP ID, Gender, Class, School, Status and
    **view / edit** links that open the record in a new tab (blank class shows
    as —).
11. The panel's open/closed state is remembered on the device: once you close
    it (×), it stays closed across page changes, new tabs and restarts —
    reopen any time with the small **B-Form Search** button (top-right).

## How it works

- On first search it fetches the portal's own list JSON in **one request**
  (DataTables server-side endpoint, up to 1000 rows per page, auto-paginated
  if the school list ever grows past that).
- The list is cached in the browser tab for 15 minutes — repeat and batch
  searches are instant. **↻ Refresh** forces a reload from the portal.
- Matching is done locally in the page (digits-normalized).
- If the portal session expires, the panel tells you to log in and reload.

## Troubleshooting

- **Panel doesn't appear** → make sure you are on `/students` and Tampermonkey
  shows the script as enabled for that site.
- **"Portal session expired"** → log in at https://femis.fde.gov.pk/login,
  then reload the list page.
- **Nothing matches** → try partial digits, or clear with ↻ Refresh (the list
  may have changed since the cache was written).
- **Tampermonkey warning: "Limited runtime host permissions…"** → generic
  notice, not a security alert. It fires because this script only runs on
  `femis.fde.gov.pk`, so Chrome grants Tampermonkey narrow site access.
  It does **not** affect searching (the script uses no GM_* APIs — only a
  plain same-origin fetch on the portal). The one feature it can affect is
  **auto-update** from the GitHub raw URL: if updates don't arrive, either
  (a) Chrome → Extensions → Tampermonkey → *Site access* → add
  `https://raw.githubusercontent.com` (or set "On all sites"), or
  (b) update manually — open the raw script URL above; Tampermonkey will
  offer the new version. The warning itself can be dismissed.

## Source of truth

`portal-search/femis-bform-search.user.js` in this repo. Bump the
`@version` line when editing so Tampermonkey propagates the update.

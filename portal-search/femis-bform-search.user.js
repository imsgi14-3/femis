// ==UserScript==
// @name         FEMIS B-Form Search
// @namespace    imsg.femis
// @version      1.6.0
// @description  Search ALL FEMIS students by B-Form / Student ID / admission no. / TMP ID / name (server-side list API, cached client-side)
// @match        https://femis.fde.gov.pk/students*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  if (document.getElementById('fbs-panel')) return;

  var CACHE_KEY = 'fbs_cache_v1';
  var CACHE_TTL_MS = 15 * 60 * 1000;
  var PAGE_LENGTH = 1000;
  var OPEN_KEY = 'fbs_open';

  function readOpenPref() {
    try { return localStorage.getItem(OPEN_KEY); } catch (e) { return null; }
  }

  function writeOpenPref(v) {
    try { localStorage.setItem(OPEN_KEY, v); } catch (e) { }
  }

  // ---- data layer ---------------------------------------------------------

  function buildParams(start, length) {
    var cols = [
      { data: 'index', name: 'index', searchable: 'false', orderable: 'false' },
      { data: 'name', name: '', searchable: 'true', orderable: 'true' },
      { data: 'b_form', name: 'b_form', searchable: 'true', orderable: 'true' },
      { data: 'gender', name: '', searchable: 'true', orderable: 'true' },
      { data: 'class.name', name: '', searchable: 'true', orderable: 'true' },
      { data: 'school.name', name: '', searchable: 'true', orderable: 'true' },
      { data: 'status', name: '', searchable: 'true', orderable: 'true' },
      { data: 'action', name: '', searchable: 'false', orderable: 'true' },
      { data: 'temporary_bform_id', name: 'students.temporary_bform_id', searchable: 'false', orderable: 'false' }
    ];
    var q = [
      'draw=' + Date.now(),
      'start=' + start,
      'length=' + length,
      'search[value]=',
      'search[regex]=false'
    ];
    for (var i = 0; i < cols.length; i++) {
      var c = cols[i];
      q.push('columns[' + i + '][data]=' + encodeURIComponent(c.data));
      if (c.name) q.push('columns[' + i + '][name]=' + encodeURIComponent(c.name));
      q.push('columns[' + i + '][searchable]=' + c.searchable);
      q.push('columns[' + i + '][orderable]=' + c.orderable);
      q.push('columns[' + i + '][search][value]=');
      q.push('columns[' + i + '][search][regex]=false');
    }
    q.push('order[0][column]=1');
    q.push('order[0][dir]=asc');
    return q.join('&');
  }

  function normalizeDigits(s) {
    return String(s || '').replace(/\D/g, '');
  }

  function stripHtml(html) {
    var d = document.createElement('div');
    d.innerHTML = String(html || '');
    return (d.textContent || '').replace(/\s+/g, ' ').trim();
  }

  async function fetchPage(start) {
    var r = await fetch('/students?' + buildParams(start, PAGE_LENGTH), {
      headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    });
    var ct = r.headers.get('content-type') || '';
    if (!r.ok || ct.indexOf('json') === -1) {
      throw new Error('SESSION');
    }
    return r.json();
  }

  async function fetchAll(onProgress) {
    var rows = [];
    var start = 0;
    for (var page = 0; page < 20; page++) {
      if (onProgress) onProgress('Loading page ' + (page + 1) + '…');
      var j = await fetchPage(start);
      var data = j.data || [];
      rows = rows.concat(data);
      if (onProgress) onProgress('Loaded ' + rows.length + ' of ' + (j.recordsFiltered || j.recordsTotal || '?') + ' students');
      if (data.length < PAGE_LENGTH) break;
      start += data.length;
      await new Promise(function (res) { setTimeout(res, 300); });
    }
    return rows;
  }

  function readCache() {
    try {
      var raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      var c = JSON.parse(raw);
      if (!c || !c.t || !Array.isArray(c.rows)) return null;
      if (Date.now() - c.t > CACHE_TTL_MS) return null;
      return c;
    } catch (e) { return null; }
  }

  function writeCache(rows) {
    try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ t: Date.now(), rows: rows })); }
    catch (e) { /* quota — cache is optional */ }
  }

  function clearCache() {
    try { sessionStorage.removeItem(CACHE_KEY); } catch (e) { }
  }

  async function getRows(force, onProgress) {
    if (!force) {
      var c = readCache();
      if (c) { onProgress('Using cached list (' + c.rows.length + ' students)'); return c.rows; }
    }
    var rows = await fetchAll(onProgress);
    writeCache(rows);
    return rows;
  }

  // ---- search layer ---------------------------------------------------------

  function matchQuery(rows, query) {
    var q = String(query || '').trim();
    if (!q) return { exact: [], partial: [], mode: 'empty' };
    var digits = normalizeDigits(q);
    var upper = q.toUpperCase();
    var exact = [], partial = [];
    if (/^TMP/i.test(q)) {
      var tq = upper;
      rows.forEach(function (row) {
        var t = String(row.temporary_bform_id || '').toUpperCase();
        if (t && t.indexOf(tq) !== -1) exact.push(row);
      });
      return { exact: exact, partial: partial, mode: 'tmp' };
    }
    var admissionDigits = function (row) {
      return row.admission_number == null ? '' : String(row.admission_number).replace(/\D/g, '');
    };
    if (digits.length >= 4) {
      // b_form exact/partial AND admission-number exact/partial in one pass,
      // deduped: a row matching both shows once, exact beats partial
      var seen = {};
      rows.forEach(function (row) {
        var k = row.uuid || row.id;
        var s = row.b_form == null ? '' : String(row.b_form);
        var a = admissionDigits(row);
        if (s === digits || a === digits) {
          if (!seen[k]) { seen[k] = 1; exact.push(row); }
        } else if ((s && s.indexOf(digits) !== -1) || (a && a.indexOf(digits) !== -1)) {
          if (!seen[k]) { seen[k] = 1; partial.push(row); }
        }
      });
      return { exact: exact, partial: partial, mode: 'bform' };
    }
    if (digits.length >= 1 && /^[0-9\s-]+$/.test(q)) {
      // short numeric query (1-3 digits): exact admission-number match
      rows.forEach(function (row) {
        if (admissionDigits(row) === digits) exact.push(row);
      });
      return { exact: exact, partial: partial, mode: 'admission' };
    }
    rows.forEach(function (row) {
      if (String(row.name || '').toUpperCase().indexOf(upper) !== -1) exact.push(row);
    });
    return { exact: exact, partial: partial, mode: 'name' };
  }

  function applyNameFilter(rows, nameFilter) {
    var f = String(nameFilter || '').trim().toUpperCase();
    if (!f) return rows;
    return rows.filter(function (row) {
      return String(row.name || '').toUpperCase().indexOf(f) !== -1;
    });
  }

  function statusLabel(row) {
    var t = stripHtml(row.status);
    if (t) return t;
    return row.is_active ? 'Active' : 'Inactive';
  }

  function applyStatusFilter(rows, val) {
    if (!val) return rows;
    var v = String(val).toUpperCase();
    return rows.filter(function (row) {
      return statusLabel(row).toUpperCase() === v;
    });
  }

  function classLabel(row) {
    return row.class && row.class.name ? String(row.class.name).trim() : '';
  }

  function applyClassFilter(rows, val) {
    if (!val) return rows;
    if (val === '__BLANK__') {
      return rows.filter(function (row) { return !classLabel(row); });
    }
    return rows.filter(function (row) { return classLabel(row) === val; });
  }

  function byName(a, b) {
    return String(a.name || '').localeCompare(String(b.name || ''));
  }

  // ---- status action ---------------------------------------------------------
  // Portal route (verified from the embedded route map):
  //   GET /students/update-status/{student}  — Toggles Active <-> Inactive.
  // Every row shows the link for the OPPOSITE direction of its current state
  // ("inactive" on Active rows, "active" on Inactive rows) and the direction
  // is re-read from the row at click time, so the label flips immediately
  // after each change and a second click always moves it back.

  function patchRowInCache(uuid, isActive) {
    try {
      var raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return;
      var c = JSON.parse(raw);
      if (!c || !Array.isArray(c.rows)) return;
      for (var i = 0; i < c.rows.length; i++) {
        var r = c.rows[i];
        if (r && r.uuid === uuid) { r.status = ''; r.is_active = isActive; break; }
      }
      sessionStorage.setItem(CACHE_KEY, JSON.stringify(c));
    } catch (e) { /* cache patch is best-effort */ }
  }

  function toggleStatus(row, linkEl) {
    if (!row || !row.uuid) return;
    var makeInactive = statusLabel(row) !== 'Inactive';
    var target = makeInactive ? 'Inactive' : 'Active';
    if (!window.confirm('Set "' + row.name + '" to ' + target + '?')) return;
    setStatus('Setting ' + row.name + ' to ' + target + '…');
    fetch('/students/update-status/' + row.uuid, { credentials: 'same-origin' })
      .then(function (resp) {
        if (resp.url && resp.url.indexOf('/login') !== -1) throw new Error('SESSION');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        row.status = '';
        row.is_active = !makeInactive;
        patchRowInCache(row.uuid, !makeInactive);
        var tr = linkEl.closest('tr');
        var cells = tr ? tr.querySelectorAll('td') : [];
        if (cells.length >= 7) cells[6].textContent = target;
        linkEl.textContent = makeInactive ? 'active' : 'inactive';
        setStatus('"' + row.name + '" is now ' + target);
      })
      .catch(function (e) {
        setStatus(String(e && e.message) === 'SESSION'
          ? 'Portal session expired — status NOT changed. Log in at /login, reload this page, then try again.'
          : 'Status change failed for "' + row.name + '": ' + (e && e.message ? e.message : e), true);
      });
  }

  // ---- UI --------------------------------------------------------------------

  var style = document.createElement('style');
  style.textContent = [
    '#fbs-panel{position:fixed;top:70px;right:16px;width:760px;max-width:95vw;max-height:85vh;',
    'background:#fff;border:2px solid #0d6efd;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.25);',
    'z-index:99999;font:13px/1.45 Segoe UI,Arial,sans-serif;color:#222;display:flex;flex-direction:column;}',
    '#fbs-panel .fbs-head{display:flex;align-items:center;gap:8px;background:#0d6efd;color:#fff;',
    'padding:8px 12px;border-radius:6px 6px 0 0;font-weight:600;}',
    '#fbs-panel .fbs-head span{flex:1;}',
    '#fbs-panel .fbs-head button{background:rgba(255,255,255,.2);border:0;color:#fff;',
    'border-radius:4px;cursor:pointer;padding:2px 9px;font-size:13px;}',
    '#fbs-panel .fbs-body{padding:10px 12px;overflow:auto;}',
    '#fbs-panel input[type=text],#fbs-panel select,#fbs-panel textarea{width:100%;box-sizing:border-box;padding:6px 8px;',
    'margin:3px 0;border:1px solid #bbb;border-radius:4px;font:inherit;}',
    '#fbs-panel .fbs-row{display:flex;gap:8px;align-items:center;margin:4px 0;}',
    '#fbs-panel .fbs-row label{white-space:nowrap;}',
    '#fbs-panel .fbs-row select{min-width:210px;}',
    '#fbs-panel #fbs-search{background:#0d6efd;color:#fff;border:0;border-radius:4px;',
    'padding:7px 18px;cursor:pointer;font:inherit;font-weight:600;}',
    '#fbs-panel #fbs-search:disabled{opacity:.55;}',
    '#fbs-panel #fbs-status{margin:6px 0;min-height:18px;color:#555;font-style:italic;}',
    '#fbs-panel #fbs-status.fbs-err{color:#b02a37;font-style:normal;font-weight:600;}',
    '#fbs-panel table{width:100%;border-collapse:collapse;margin-top:4px;}',
    '#fbs-panel th,#fbs-panel td{border:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top;}',
    '#fbs-panel th{background:#f2f4f7;position:sticky;top:0;}',
    '#fbs-panel tr.fbs-partial td{background:#fff8e6;}',
    '#fbs-panel a{color:#0d6efd;}',
    '#fbs-panel .fbs-section{font-weight:700;margin:10px 0 2px;}',
    '#fbs-toggle{position:fixed;top:70px;right:16px;z-index:99999;background:#0d6efd;color:#fff;',
    'border:0;border-radius:18px;padding:8px 14px;cursor:pointer;font:600 13px Segoe UI,Arial;',
    'box-shadow:0 4px 14px rgba(0,0,0,.3);}',
    '#fbs-panel #fbs-batch-ta{height:72px;display:none;}'
  ].join('');
  document.head.appendChild(style);

  var toggle = document.createElement('button');
  toggle.id = 'fbs-toggle';
  toggle.textContent = 'B-Form Search';
  toggle.addEventListener('click', function () {
    writeOpenPref('1');
    toggle.style.display = 'none';
    panel.style.display = 'flex';
    warm();
  });
  document.body.appendChild(toggle);

  var panel = document.createElement('div');
  panel.id = 'fbs-panel';
  panel.innerHTML = [
    '<div class="fbs-head"><span>FEMIS B-Form Search</span>',
    '<button id="fbs-refresh" title="Reload list from portal">&#8635; Refresh</button>',
    '<button id="fbs-close" title="Hide panel">&times;</button></div>',
    '<div class="fbs-body">',
    '<input type="text" id="fbs-q" placeholder="B-Form / admission no. / TMP ID / student name (min 4 chars for name)">',
    '<input type="text" id="fbs-name" placeholder="Optional: filter results by name">',
    '<div class="fbs-row"><label>Status: <select id="fbs-status-filter">',
    '<option value="">Any status</option>',
    '<option value="Active">Active</option>',
    '<option value="Inactive">Inactive</option>',
    '</select></label></div>',
    '<div class="fbs-row"><label>Class: <select id="fbs-class-filter">',
    '<option value="">Any class</option>',
    '</select></label></div>',
    '<div class="fbs-row"><label><input type="checkbox" id="fbs-batch"> Batch mode (one B-Form / TMP / admission no. per line)</label></div>',
    '<textarea id="fbs-batch-ta" placeholder="3740245784474&#10TMP-2026-36033"></textarea>',
    '<div class="fbs-row"><button id="fbs-search">Search</button></div>',
    '<div id="fbs-status"></div>',
    '<div id="fbs-results"></div>',
    '</div>'
  ].join('');
  document.body.appendChild(panel);

  // Restore open/closed preference: once the user closes the panel it stays
  // closed across URL changes, new tabs and restarts (localStorage) until
  // they click the B-Form Search toggle again. First-ever load: open.
  if (readOpenPref() === '0') {
    panel.style.display = 'none';
    toggle.style.display = 'block';
  } else {
    panel.style.display = 'flex';
    toggle.style.display = 'none';
  }

  var $ = function (id) { return document.getElementById(id); };
  var statusEl = $('fbs-status');
  var resultsEl = $('fbs-results');
  var searchBtn = $('fbs-search');
  var batchChk = $('fbs-batch');
  var batchTa = $('fbs-batch-ta');

  $('fbs-close').addEventListener('click', function () {
    writeOpenPref('0');
    panel.style.display = 'none';
    toggle.style.display = 'block';
  });
  $('fbs-refresh').addEventListener('click', function () { runSearch(true); });
  batchChk.addEventListener('change', function () {
    batchTa.style.display = batchChk.checked ? 'block' : 'none';
  });
  $('fbs-q').addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !batchChk.checked) runSearch(false);
  });

  function setStatus(text, isErr) {
    statusEl.textContent = text || '';
    statusEl.className = isErr ? 'fbs-err' : '';
  }

  function populateClassFilter(rows) {
    var sel = $('fbs-class-filter');
    if (!sel) return;
    var counts = {}, blank = 0;
    rows.forEach(function (row) {
      var l = classLabel(row);
      if (l) counts[l] = (counts[l] || 0) + 1;
      else blank++;
    });
    var names = Object.keys(counts).sort(function (a, b) {
      return a.localeCompare(b, undefined, { numeric: true });
    });
    var prev = sel.value;
    while (sel.firstChild) sel.removeChild(sel.firstChild);
    function addOpt(val, text) {
      var o = document.createElement('option');
      o.value = val;
      o.textContent = text;
      sel.appendChild(o);
    }
    addOpt('', 'Any class (' + rows.length + ')');
    names.forEach(function (n) { addOpt(n, n + ' (' + counts[n] + ')'); });
    addOpt('__BLANK__', 'Blank (no class) (' + blank + ')');
    if (prev) {
      for (var i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === prev) { sel.value = prev; break; }
      }
    }
  }

  function makeCell(row, text, isPartial) {
    var td = document.createElement('td');
    td.textContent = text == null ? '' : String(text);
    if (isPartial) td.className = 'fbs-partial';
    return td;
  }

  function resultTable(rows, isPartial) {
    var table = document.createElement('table');
    var thead = document.createElement('thead');
    var htr = document.createElement('tr');
    ['Name', 'B-Form', 'TMP ID', 'Gender', 'Class', 'School', 'Status', 'Record'].forEach(function (h) {
      var th = document.createElement('th');
      th.textContent = h;
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);
    var tbody = document.createElement('tbody');
    rows.forEach(function (row) {
      var tr = document.createElement('tr');
      if (isPartial) tr.className = 'fbs-partial';
      tr.appendChild(makeCell(row, row.name, isPartial));
      tr.appendChild(makeCell(row, row.b_form == null ? '—' : row.b_form, isPartial));
      tr.appendChild(makeCell(row, row.temporary_bform_id || '—', isPartial));
      tr.appendChild(makeCell(row, row.gender, isPartial));
      tr.appendChild(makeCell(row, classLabel(row) || '—', isPartial));
      tr.appendChild(makeCell(row, row.school && row.school.name ? row.school.name : '', isPartial));
      tr.appendChild(makeCell(row, statusLabel(row), isPartial));
      var td = document.createElement('td');
      if (row.uuid) {
        var view = document.createElement('a');
        view.href = '/students/' + row.uuid;
        view.target = '_blank';
        view.textContent = 'view';
        var edit = document.createElement('a');
        edit.href = '/students/' + row.uuid + '/edit';
        edit.target = '_blank';
        edit.textContent = 'edit';
        td.appendChild(view);
        td.appendChild(document.createTextNode(' | '));
        td.appendChild(edit);
        td.appendChild(document.createTextNode(' | '));
        var stat = document.createElement('a');
        stat.href = '#';
        stat.className = 'fbs-status-act';
        stat.textContent = statusLabel(row) === 'Inactive' ? 'active' : 'inactive';
        stat.addEventListener('click', function (ev) {
          ev.preventDefault();
          toggleStatus(row, stat);
        });
        td.appendChild(stat);
      }
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  function renderGroup(container, label, res) {
    if (res.exact.length) {
      var h1 = document.createElement('div');
      h1.className = 'fbs-section';
      h1.textContent = label + ' — ' + res.exact.length + ' exact match' + (res.exact.length === 1 ? '' : 'es');
      container.appendChild(h1);
      container.appendChild(resultTable(res.exact.slice().sort(byName), false));
    }
    if (res.partial.length) {
      var h2 = document.createElement('div');
      h2.className = 'fbs-section';
      h2.textContent = label + ' — ' + res.partial.length + ' partial match' + (res.partial.length === 1 ? '' : 'es') + ' (contains the digits)';
      container.appendChild(h2);
      container.appendChild(resultTable(res.partial.slice().sort(byName), true));
    }
  }

  async function runSearch(force) {
    searchBtn.disabled = true;
    resultsEl.textContent = '';
    try {
      var all = await getRows(force, function (p) { setStatus(p); });
      populateClassFilter(all);
      var rows = applyStatusFilter(all, $('fbs-status-filter').value);
      rows = applyClassFilter(rows, $('fbs-class-filter').value);
      setStatus('List ready: ' + rows.length +
        (rows.length !== all.length ? ' of ' + all.length : '') + ' students');
      if (batchChk.checked) {
        var lines = batchTa.value.split(/\r?\n/).map(function (l) { return l.trim(); }).filter(Boolean);
        if (!lines.length) { setStatus('Batch list is empty', true); return; }
        var total = 0;
        lines.forEach(function (line) {
          var res = matchQuery(rows, line);
          res.exact = applyNameFilter(res.exact, '');
          if (!res.exact.length && !res.partial.length) {
            var h = document.createElement('div');
            h.className = 'fbs-section';
            h.textContent = line + ' — no matches';
            resultsEl.appendChild(h);
            return;
          }
          renderGroup(resultsEl, line, res);
          total += res.exact.length;
        });
        setStatus(lines.length + ' queries, ' + total + ' exact match(es)');
        return;
      }
      var q = $('fbs-q').value;
      var statusVal = $('fbs-status-filter').value;
      var classVal = $('fbs-class-filter').value;
      var nameVal = $('fbs-name').value;
      if (!q.trim()) {
        // filter-only mode: Status/Class/Name filter alone drives the results
        // (show ALL inactive, ALL blank-class, etc. without entering a B-Form)
        if (!statusVal && !classVal && !nameVal.trim()) {
          setStatus('Enter a B-Form, TMP ID, or name', true);
          return;
        }
        var frows = applyNameFilter(rows, nameVal);
        if (!frows.length) {
          setStatus('No students match the selected filters');
          return;
        }
        var parts = [];
        if (statusVal) parts.push('Status: ' + statusVal);
        if (classVal) parts.push('Class: ' + (classVal === '__BLANK__' ? 'Blank (no class)' : classVal));
        if (nameVal.trim()) parts.push('Name contains "' + nameVal.trim() + '"');
        var fh = document.createElement('div');
        fh.className = 'fbs-section';
        fh.textContent = parts.join(' | ') + ' — ' + frows.length + ' student' + (frows.length === 1 ? '' : 's');
        resultsEl.appendChild(fh);
        resultsEl.appendChild(resultTable(frows.slice().sort(byName), false));
        setStatus(frows.length + ' of ' + all.length + ' students shown');
        return;
      }
      var result = matchQuery(rows, q);
      result.exact = applyNameFilter(result.exact, $('fbs-name').value);
      result.partial = applyNameFilter(result.partial, $('fbs-name').value);
      if (!result.exact.length && !result.partial.length) {
        setStatus('No matches for "' + q + '"');
        return;
      }
      renderGroup(resultsEl, q, result);
      setStatus(result.exact.length + ' exact, ' + result.partial.length + ' partial — ' + all.length + ' students scanned');
    } catch (e) {
      if (String(e && e.message) === 'SESSION') {
        setStatus('Portal session expired or not logged in. Log in at /login, then reload this page.', true);
      } else {
        setStatus('Search failed: ' + (e && e.message ? e.message : e), true);
      }
    } finally {
      searchBtn.disabled = false;
    }
  }

  var warming = false;

  function warm() {
    if (warming || panel.style.display === 'none') return;
    var c = readCache();
    if (c) {
      populateClassFilter(c.rows);
      setStatus('List ready: ' + c.rows.length + ' students (cached)');
      return;
    }
    warming = true;
    setStatus('Loading student list…');
    getRows(false, function (p) { setStatus(p); })
      .then(function (rows) {
        populateClassFilter(rows);
        setStatus('List ready: ' + rows.length + ' students');
      })
      .catch(function (e) {
        setStatus(String(e && e.message) === 'SESSION'
          ? 'Portal session expired or not logged in. Log in at /login, then reload this page.'
          : 'Could not load student list: ' + (e && e.message ? e.message : e), true);
      })
      .finally(function () { warming = false; });
  }

  searchBtn.addEventListener('click', function () { runSearch(false); });
  $('fbs-q').focus();
  warm();
})();

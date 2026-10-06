"""Student list export — Excel (openpyxl) and PDF (fpdf2) with user-picked columns.

The column catalog is derived from config/field_mapping.yaml: every mapped
field whose source_field resolves to a real Student column becomes an
exportable option, labelled with its form label, grouped by form tab.  A
curated "Student" core group comes first (identity + status columns) and a
"Record" group last (ids/timestamps).  Fields whose yaml options are exactly
Yes/No render as Yes/No in the export (the form stores them as "1"/"0").
"""
import io
import re
from datetime import date, datetime
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from fpdf import FPDF
from fpdf.fonts import FontFace

FIELD_MAP_PATH = Path(__file__).parent.parent / "config" / "field_mapping.yaml"
FORM_HTML_PATH = Path(__file__).parent / "templates" / "form.html"

# Curated identity/status group shown first — these columns are what a
# teacher scans first, and they exist even when the yaml has no entry.
_CORE_FIELDS = [
    ("name", "Name"),
    ("class_id", "Class"),
    ("section_id", "Section"),
    ("roll_no", "Roll No"),
    ("b_form", "B-Form / CNIC"),
    ("gender", "Gender"),
    ("date_of_birth", "Date of Birth"),
    ("father_name", "Father Name"),
    ("contact_number", "Contact Number"),
    ("submitted", "Submitted"),
    ("locked", "Locked"),
]
_RECORD_FIELDS = [
    ("id", "Record ID"),
    ("created_at", "Created At"),
    ("updated_at", "Updated At"),
]
DEFAULT_COLUMNS = [c for c, _ in _CORE_FIELDS]

_PANE_RE = re.compile(
    r'<div\b(?=[^>]*\bclass="[^"]*tab-pane)[^>]*\bid="(tab-\d+)"')
_NAV_RE = re.compile(r'href="#(tab-\d+)">([^<]+)</a>')
_FIELD_RE = re.compile(r'<(?:input|select|textarea)\b[^>]*?\bname="([^"]+)"',
                       re.IGNORECASE)


def _form_panes():
    """[(title, [input names])] for the form's pill panes, in tab order.

    Splits templates/form.html at each `tab-pane` div (the panes are
    siblings, so the next pane start ends the previous one) and titles each
    group from its nav-pill label ("1. Personal Details" -> "Personal
    Details").  The slice of the last pane stops at </form> so nothing
    outside the form can leak in.
    """
    src = FORM_HTML_PATH.read_text(encoding="utf-8")
    titles = {pid: re.sub(r"^\d+\.\s*", "", text).strip()
              for pid, text in _NAV_RE.findall(src)}
    starts = [(m.start(), m.group(1)) for m in _PANE_RE.finditer(src)]
    form_end = src.find("</form>")
    if form_end == -1:
        form_end = len(src)
    panes = []
    for i, (pos, pid) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(src)
        end = min(end, form_end)
        names, seen = [], set()
        for name in _FIELD_RE.findall(src[pos:end]):
            if name in seen or "{{" in name:
                continue
            seen.add(name)
            names.append(name)
        panes.append((titles.get(pid, pid), names))
    return panes


def _pretty(label):
    label = str(label or "").strip()
    return label.replace("_", " ") if "_" in label and " " not in label else label


def build_catalog(student_columns, form_field_map):
    """([(group_title, [(column, label), ...])], yesno_columns).

    `student_columns` — set of real Student column names.
    `form_field_map`  — app.FORM_FIELD_MAP (form name -> DB column renames).

    Grouping follows the actual form: form.html's seven pill panes are the
    authoritative field->tab layout (the yaml mixes discovery tail-dumps
    across tabs, so it cannot decide ownership).  Labels, Yes/No flags and
    the key->source_field mapping still come from the yaml; columns the
    form never renders (ids, timestamps, hidden mirrors) collect under
    "Record".
    """
    doc = yaml.safe_load(FIELD_MAP_PATH.read_text(encoding="utf-8")) or {}
    student_columns = set(student_columns) - {"role"}

    label_by_col = {}   # Student column -> display label (first yaml wins)
    yesno = {"submitted", "locked"}
    for tab in doc.values():
        if not isinstance(tab, dict):
            continue
        for key, cfg in tab.items():
            if not isinstance(cfg, dict):
                continue
            label = _pretty(cfg.get("label") or "")
            sf = cfg.get("source_field")
            if isinstance(sf, str) and sf:
                col = form_field_map.get(sf, sf)
                if col in student_columns and label:
                    label_by_col.setdefault(col, label)
                opts = cfg.get("options")
                if (isinstance(opts, list)
                        and set(map(str, opts)) == {"Yes", "No"}):
                    yesno.add(col)
            if label:
                col_key = form_field_map.get(key, key)
                if col_key in student_columns:
                    label_by_col.setdefault(col_key, label)

    seen = set()
    groups = []
    core_items = []
    for col, label in _CORE_FIELDS:
        if col in student_columns and col not in seen:
            seen.add(col)
            core_items.append((col, label))
    groups.append(("Student", core_items))

    def resolve(name):
        """Same name->column rule as save-tab's _map_form_data."""
        col = form_field_map.get(name, name)
        if isinstance(col, str) and col in student_columns:
            return col
        stripped = name.replace("[]", "")
        col = form_field_map.get(stripped, stripped)
        if isinstance(col, str) and col in student_columns:
            return col
        return None

    for title, names in _form_panes():
        items = []
        for name in names:
            col = resolve(name)
            if col is None or col in seen:
                continue
            seen.add(col)
            label = label_by_col.get(col) or _pretty(name.replace("[]", ""))
            items.append((col, label))
        if items:
            groups.append((title, items))

    record = [(c, l) for c, l in _RECORD_FIELDS
              if c in student_columns and c not in seen]
    seen.update(c for c, _ in record)
    rest = [(c, _pretty(c)) for c in sorted(student_columns) if c not in seen]
    if record or rest:
        groups.append(("Record", record + rest))
    return groups, yesno


def cell_value(student, column, yesno=False):
    v = getattr(student, column, None)
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if yesno and str(v) in ("1", "0"):
        return "Yes" if str(v) == "1" else "No"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v)


def students_to_xlsx(rows, columns, labels, yesno=frozenset()):
    wb = Workbook()
    ws = wb.active
    ws.title = "Students"
    ws.append(labels)
    header_font = Font(bold=True)
    for cell in ws[1]:
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    for s in rows:
        ws.append([cell_value(s, c, c in yesno) for c in columns])
    for idx, label in enumerate(labels, start=1):
        width = len(str(label))
        for s in rows[:200]:
            width = max(width, len(cell_value(s, columns[idx - 1],
                                              columns[idx - 1] in yesno)))
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = \
            min(max(width + 2, 8), 50)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


_PDF_MAX_CHARS = 90


def students_to_pdf(rows, columns, labels, title, yesno=frozenset()):
    pdf = FPDF(orientation="L", format="A4")
    # auto page break must stay ON: with it off the table rendered exactly
    # one page and every row past it was silently dropped (~22 rows).
    pdf.set_auto_page_break(True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, f"{len(rows)} student(s) - generated "
                   f"{datetime.now().strftime('%Y-%m-%d %H:%M')}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)
    n = len(columns)
    size = 8 if n <= 9 else (6.5 if n <= 15 else (5.5 if n <= 25 else 4.5))
    pdf.set_font("Helvetica", "", size)
    with pdf.table(
            col_widths=[1] * n,
            text_align="LEFT",
            first_row_as_headings=True,
            headings_style=FontFace(emphasis="BOLD", size_pt=size),
            padding=1.2,
    ) as table:
        row = table.row()
        for label in labels:
            row.cell(str(label))
        for s in rows:
            row = table.row()
            for c in columns:
                v = cell_value(s, c, c in yesno)
                if len(v) > _PDF_MAX_CHARS:
                    v = v[:_PDF_MAX_CHARS - 1] + "..."
                row.cell(v)
    return io.BytesIO(bytes(pdf.output()))

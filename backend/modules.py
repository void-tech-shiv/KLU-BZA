"""Allowlisted, read-only ERP pages. No generic URL proxy or raw HTML output."""
import re

from . import erp

# Fixed destinations: no client-supplied routes, URL fragments or query values.
MODULES = {
    'cgpa': ('Overall CGPA', '/index.php?r=studentinfo%2Fstudentendexamresult%2Fsearchgetmycgpa'),
    'timetable': ('Timetable', '/index.php?r=timetables%2Funiversitymasteracademictimetableview%2Findexstudentindisearch'),
    'seating': ('Exam seating', '/index.php?r=examsection%2Fexam-invigilator-student-room-allotment-info%2Fstud_my_seating_plan'),
    'profile': ('Student profile', '/index.php?r=studentinfo%2Fstudentprofileinfo%2Fviewprofileindi'),
}

REDACT_KEYS = re.compile(r'password|captcha|csrf|session|bearer|auth.?token|otp|secret|cookie', re.I)


def text_of(el):
    return ' '.join(el.stripped_strings)[:180]


def parse_readonly_page(html):
    """Extract only visible textual tables/key-value labels, not markup/scripts.

    Empty or unrecognized pages fail explicitly, avoiding invented GPA or seat data.
    Caps limit the exposure and memory footprint of unexpectedly large pages.
    """
    document = erp.soup(html)
    if erp.has_login_form(html):
        raise erp.ERPError('ERP sign-in session expired. Please sign in again.')
    for el in document.select('script,style,noscript,template,form,input,textarea'):
        el.decompose()
    tables = []
    for table in document.select('table'):
        if len(tables) >= 5:
            break
        if table.find_parent(['nav','footer','aside']):
            continue
        trs = table.select('tr')[:62]
        if not trs:
            continue
        header = table.select_one('thead tr')
        headings = [text_of(c) for c in header.find_all(['th','td'], recursive=False)] if header else []
        rows = []
        for tr in trs:
            if header is not None and tr is header:
                continue
            cells = [text_of(c) for c in tr.find_all(['td','th'], recursive=False)]
            if 2 <= len(cells) <= 10 and any(cells):
                rows.append(cells)
        if not rows:
            continue
        # Headerless simple key-value layout: do not invent course names.
        if not headings and all(len(x) == 2 for x in rows):
            headings = ['Field', 'Value']
        if not (2 <= len(headings) <= 10):
            continue
        safe_rows = [r for r in rows
                     if len(r) == len(headings)
                     and not REDACT_KEYS.search(' '.join(r[:1]))][:50]
        if not safe_rows or any(REDACT_KEYS.search(h) for h in headings):
            continue
        tables.append({'columns': headings, 'rows': safe_rows})
    if not tables:
        fields = []
        for dt in document.select('dt')[:50]:
            dd = dt.find_next_sibling('dd')
            if dd is None:
                continue
            key, val = text_of(dt), text_of(dd)
            if key and val and not REDACT_KEYS.search(key):
                fields.append([key, val])
        if fields:
            tables.append({'columns': ['Field', 'Value'], 'rows': fields})
    if not tables:
        raise erp.ERPError(
            'ERP page is reachable but its data layout is not yet supported. '
            'Open the official ERP page to view it.')
    return tables

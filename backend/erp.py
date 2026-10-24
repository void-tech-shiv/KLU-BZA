"""Read-only ERP adapter. Never persists credentials or accepts arbitrary upstream URLs."""
import re
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode, urlunsplit
from bs4 import BeautifulSoup
import httpx

ORIGIN = 'https://newerp.kluniversity.in'
class ERPError(Exception):
    pass

def safe_url(path):
    url = urljoin(ORIGIN + '/', path)
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'newerp.kluniversity.in' or p.username or p.password:
        raise ERPError('ERP returned an unexpected destination.')
    return url

async def request(client, method, path, **kwargs):
    url = safe_url(path)
    if 'params' in kwargs:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        query.update(kwargs.pop('params'))
        url = urlunsplit(parts._replace(query=urlencode(query)))
    for _ in range(6):
        r = await client.request(method, url, **kwargs)
        if r.status_code in (301, 302, 303, 307, 308):
            url = safe_url(urljoin(url, r.headers.get('location', '')))
            if r.status_code in (301, 302, 303):
                method, kwargs = 'GET', {}
            continue
        if r.status_code == 429:
            raise ERPError('ERP is busy. Please wait a minute before retrying.')
        r.raise_for_status()
        if len(r.content) > 4_000_000:
            raise ERPError('ERP response exceeds the supported size.')
        return r
    raise ERPError('ERP redirected too many times.')

def soup(html):
    return BeautifulSoup(html, 'html.parser')

def login_form(html):
    document = soup(html)
    required = ('LoginForm[username]', 'LoginForm[password]', 'LoginForm[captcha]')
    # Some Yii themes omit the form id; the three expected field names remain mandatory.
    form = next(
        (f for f in document.select('form')
         if all(f.find('input', attrs={'name': name}) is not None for name in required)),
        None,
    )
    if form is None:
        raise ERPError('ERP login fields could not be verified. Please use the official ERP.')
    img = (form.select_one('#loginFormCaptcha-image')
           or form.select_one('img[src*="captcha" i]')
           or form.select_one('img[data-src*="captcha" i]')
           or form.select_one('img[id*="captcha" i]'))
    image_src = (img.get('src') or img.get('data-src')) if img else None
    if not image_src:
        raise ERPError('ERP CAPTCHA source could not be identified. Please use the official ERP.')
    hidden = {i['name']: i.get('value', '') for i in form.select('input[type=hidden][name]')}
    return safe_url(form.get('action', '/')), hidden, safe_url(image_src)


def captcha_image(response):
    """Accept small, actual raster images, never HTML error pages or SVG."""
    data = response.content
    mime = response.headers.get('content-type', '').split(';')[0].strip().lower()
    signatures = {
        'image/png': data.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/jpeg': data.startswith(b'\xff\xd8\xff'),
        'image/gif': data.startswith((b'GIF87a', b'GIF89a')),
        'image/webp': len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP',
    }
    if not data or len(data) > 256_000 or not signatures.get(mime, False):
        raise ERPError('ERP returned an invalid CAPTCHA image. Tap New CAPTCHA to retry.')
    return data


def has_login_form(html):
    return soup(html).find('input', attrs={'name': 'LoginForm[password]'}) is not None


def authenticated(html):
    """Require positive sign-in evidence, never infer it from a redirect alone."""
    document = soup(html)
    if document.find('input', attrs={'name': 'LoginForm[password]'}) is not None:
        return False
    return any('logout' in item.get(attr, '').lower()
               for attr, selector in (('href', 'a[href]'), ('action', 'form[action]'))
               for item in document.select(selector))


def login_failure_reason(html):
    """Read only validation structure, not user input or error text.

    Yii form field errors are safe to classify into generic categories.
    Do NOT include raw upstream HTML/error strings in responses or logs.
    """
    document = soup(html)
    if document.find('input', attrs={'name': 'LoginForm[password]'}) is None:
        return 'unconfirmed'

    def invalid_field(name):
        field = document.select_one('#field-loginform-' + name)
        if field is None:
            return False
        classes = set(field.get('class', []))
        if classes.intersection(('has-error', 'is-invalid', 'error')):
            return True
        if field.select_one('[aria-invalid="true"], input.is-invalid, .invalid-feedback'):
            return True
        return any(
            node.get_text(' ', strip=True)
            for node in field.select('.help-block, .help-block-error, .error-message')
        )

    if invalid_field('captcha'):
        return 'captcha'
    if invalid_field('username') or invalid_field('password'):
        return 'credentials'
    return 'unconfirmed'

def attendance_link(html):
    for a in soup(html).select('a[href]'):
        label = (a.get_text(' ', strip=True) + ' ' + a.get('title', '')).lower()
        if 'attendance register' in label:
            return safe_url(a['href'])
    raise ERPError('Attendance menu not identified. A sanitized attendance-page HTML sample is needed.')

def known_attendance_search(url):
    """Recognize a known read-only ERP attendance form route, not arbitrary links."""
    from urllib.parse import parse_qs
    canonical = safe_url(url)
    parts = urlsplit(canonical)
    route = parse_qs(parts.query).get('r', [])
    return (parts.path == '/index.php'
            and route == ['studentattendance/studentdailyattendance/searchgetinput'])


def attendance_form(html, page_url):
    s = soup(html)
    for f in s.find_all('form'):
        selects = f.select('select[name]')
        year = next((x for x in selects if 'academic' in (x.get('name','') + x.get('id','')).lower()), None)
        sem = next((x for x in selects if 'sem' in (x.get('name','') + x.get('id','')).lower()), None)
        if year is not None and sem is not None:
            def options(x):
                return [{'value': o.get('value', ''), 'label': o.get_text(' ', strip=True)}
                        for o in x.select('option') if o.get('value', '') != '']
            # HTML browsers include the clicked named submit button with the form.
            # In Yii pages this can be e.g. yt0=Search; omitting it may return
            # only the filters, with no attendance table at all.
            submit = {}
            candidates = []
            for button in f.select('button, input'):
                tag = button.name.lower()
                control_type = button.get('type', 'submit' if tag == 'button' else 'text').lower()
                if control_type != 'submit' or button.has_attr('disabled'):
                    continue
                name = button.get('name', '')
                label = (button.get('value', '') or button.get_text(' ', strip=True)).strip()
                if not re.fullmatch(r'[a-zA-Z0-9_\[\].-]{1,80}', name):
                    continue
                # Only recognized search actions; never forward another action
                # such as Delete/Export/Print or a value containing student data.
                if re.fullmatch(r'(search|show|view|submit|get attendance|view attendance)', label, flags=re.I):
                    candidates.append((name, button.get('value', '') or label))
            if len(candidates) == 1:
                submit = {candidates[0][0]: candidates[0][1]}
            return {'url': safe_url(urljoin(page_url, f.get('action') or page_url)),
                    'method': f.get('method', 'get').upper(),
                    'hidden': {i['name']: i.get('value', '') for i in f.select('input[type=hidden][name]')},
                    'submit': submit, 'referer': safe_url(page_url),
                    'year_name': year['name'], 'semester_name': sem['name'],
                    'years': options(year), 'semesters': options(sem)}
    raise ERPError('Attendance filters not recognized. Integration needs a sanitized page sample.')

def attendance_layout_code(html, form):
    """Expose ONLY response structure, never personal ERP HTML or field values.

    A limited, fixed-alphabet diagnostic for the student to report after a
    failed attendance refresh. No secrets, course names, IDs, URLs, or scripts.
    """
    doc = soup(html)
    scripts = ' '.join(t.get_text(' ', strip=False)[:200000]
                       for t in doc.select('script')).lower()
    js = any(marker in scripts for marker in
             ('pjax', 'yiigridview', '.ajax(', 'fetch(', 'xmlhttprequest'))
    js = js or bool(doc.select('[data-pjax], [data-ajax], [data-pjax-container]'))
    tables = min(len(doc.select('table')), 9)
    selects = min(len(doc.select('select')), 9)
    method = {'GET': 'G', 'POST': 'P'}.get(form.get('method'), 'U')
    submit = 'Y' if form.get('submit') else 'N'
    return f'AT-{method}{submit}-T{tables}-D{selects}-J{int(js)}'


def parse_attendance(html):
    """Map semantic headings; never guess percentages or merge L/P/S rows."""
    norm = lambda x: re.sub('[^a-z0-9]', '', x.lower())
    aliases = {
        'code': ['coursecode'],
        'name': ['coursedesc', 'coursedescription', 'coursename', 'coursetitle'],
        'component': ['ltps', 'component', 'classcomponent'],
        'conducted': ['totalconducted', 'conductedhours', 'totalconductedhours',
                      'classesconducted', 'hoursconducted'],
        'attended': ['totalattended', 'attendedhours', 'totalattendedhours',
                     'classesattended', 'hoursattended'],
    }
    # Some AJAX endpoints respond with an HTML fragment wrapped as JSON.
    # Only process known single-level HTML-bearing keys. Never log the payload.
    if isinstance(html, str) and html.lstrip().startswith('{'):
        import json
        try:
            wrapper = json.loads(html)
        except (ValueError, TypeError):
            wrapper = None
        if isinstance(wrapper, dict):
            for key in ('html', 'content', 'table', 'data'):
                fragment = wrapper.get(key)
                if isinstance(fragment, str) and '<table' in fragment.lower():
                    html = fragment
                    break
    document = soup(html)
    if document.select('.pagination .next:not(.disabled) a[href]'):
        raise ERPError('Attendance spans multiple pages. Pagination needs verification before showing totals.')
    for table in document.find_all('table'):
        heads = [norm(h.get_text(' ', strip=True)) for h in table.select('thead th')]
        if not heads:
            first = table.find('tr')
            heads = [norm(h.get_text(' ', strip=True)) for h in first.find_all(['th','td'])] if first else []
        indexes = {k: next((i for i,h in enumerate(heads) if h in names), None) for k,names in aliases.items()}
        if any(indexes[k] is None for k in ('code', 'name', 'conducted', 'attended')):
            continue
        # Component may be genuinely absent on a course-level aggregate.
        # Preserve that absence instead of inventing an L/P/S category.
        required_last = max(indexes[k] for k in ('code', 'name', 'conducted', 'attended'))
        rows = []
        for tr in table.select('tbody tr') or table.select('tr')[1:]:
            cells = tr.find_all('td', recursive=False)
            if len(cells) <= required_last:
                continue
            row = {
                k: cells[indexes[k]].get_text(' ', strip=True)
                for k in ('code', 'name', 'conducted', 'attended')
            }
            row['component'] = (
                cells[indexes['component']].get_text(' ', strip=True)
                if indexes['component'] is not None and len(cells) > indexes['component']
                else 'Unspecified'
            )
            try:
                for k in ('conducted', 'attended'):
                    row[k] = int(row[k].replace(',', ''))
            except ValueError:
                raise ERPError('Unexpected attendance counts; refusing to show incorrect data.')
            if not 0 <= row['attended'] <= row['conducted']:
                raise ERPError('ERP attendance counts need manual review.')
            row['percentage'] = round(row['attended'] * 100 / row['conducted'], 2) if row['conducted'] else None
            rows.append(row)
        if not rows and not any(t in table.get_text().lower() for t in ['no results', 'no records', 'no data']):
            raise ERPError('Attendance table has no recognizable rows.')
        return rows
    # Do not pretend an empty filter/search page means 0% attendance.
    # Error descriptions are structural only: never expose raw ERP HTML,
    # student identifiers, field values or cookie/session metadata.
    if document.select('select[name]'):
        raise ERPError(
            'ERP returned attendance filters but no readable course table. '
            'The Search form may use a different submission/AJAX workflow. '
            'No attendance figures were guessed.')
    if document.find_all('table'):
        raise ERPError(
            'ERP returned a table with unfamiliar attendance columns. '
            'No attendance figures were guessed.')
    raise ERPError(
        'ERP returned no attendance table for the selected year and semester. '
        'No attendance figures were guessed.')

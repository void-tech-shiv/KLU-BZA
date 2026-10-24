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
    form = soup(html).select_one('form#login-form')
    if not form:
        raise ERPError('ERP login layout changed. Please use the official ERP.')
    hidden = {i['name']: i.get('value', '') for i in form.select('input[type=hidden][name]')}
    img = form.select_one('#loginFormCaptcha-image')
    required = ['LoginForm[username]', 'LoginForm[password]', 'LoginForm[captcha]']
    if not img or any(not form.find('input', attrs={'name': n}) for n in required):
        raise ERPError('ERP login fields could not be verified.')
    return safe_url(form.get('action', '/')), hidden, safe_url(img['src'])

def authenticated(html):
    s = soup(html)
    return not s.select_one('form#login-form') and any(
        'logout' in a.get('href', '').lower() for a in s.select('a[href]'))

def attendance_link(html):
    for a in soup(html).select('a[href]'):
        label = (a.get_text(' ', strip=True) + ' ' + a.get('title', '')).lower()
        if 'attendance register' in label:
            return safe_url(a['href'])
    raise ERPError('Attendance menu not identified. A sanitized attendance-page HTML sample is needed.')

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
            return {'url': safe_url(urljoin(page_url, f.get('action') or page_url)),
                    'method': f.get('method', 'get').upper(),
                    'hidden': {i['name']: i.get('value', '') for i in f.select('input[type=hidden][name]')},
                    'year_name': year['name'], 'semester_name': sem['name'],
                    'years': options(year), 'semesters': options(sem)}
    raise ERPError('Attendance filters not recognized. Integration needs a sanitized page sample.')

def parse_attendance(html):
    """Map semantic headings; never guess percentages or merge L/P/S rows."""
    norm = lambda x: re.sub('[^a-z0-9]', '', x.lower())
    aliases = {'code': ['coursecode'], 'name': ['coursedesc', 'coursedescription', 'coursename'],
               'component': ['ltps'], 'conducted': ['totalconducted'], 'attended': ['totalattended']}
    document = soup(html)
    if document.select('.pagination .next:not(.disabled) a[href]'):
        raise ERPError('Attendance spans multiple pages. Pagination needs verification before showing totals.')
    for table in document.find_all('table'):
        heads = [norm(h.get_text(' ', strip=True)) for h in table.select('thead th')]
        if not heads:
            first = table.find('tr')
            heads = [norm(h.get_text(' ', strip=True)) for h in first.find_all(['th','td'])] if first else []
        indexes = {k: next((i for i,h in enumerate(heads) if h in names), None) for k,names in aliases.items()}
        if any(v is None for v in indexes.values()):
            continue
        rows = []
        for tr in table.select('tbody tr') or table.select('tr')[1:]:
            cells = tr.find_all('td', recursive=False)
            if len(cells) <= max(indexes.values()):
                continue
            row = {k: cells[i].get_text(' ', strip=True) for k,i in indexes.items()}
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
    raise ERPError('Attendance table not recognized. No data has been fabricated.')

import asyncio
import base64
import pytest
import httpx
from fastapi.testclient import TestClient
from backend import erp, main

LOGIN = '''<form id="login-form" action="/index.php?r=site%2Flogin"><input type="hidden" name="_csrf" value="csrf"><input name="LoginForm[username]"><input name="LoginForm[password]"><input name="LoginForm[captcha]"><img id="loginFormCaptcha-image" src="/captcha"></form>'''
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8//8/AwMDEwMDAwMDAwAkBgMB/DXemwAAAABJRU5ErkJggg==')
TABLE = '''<table><thead><tr><th>Coursecode</th><th>Coursedesc</th><th>Ltps</th><th>Total Conducted</th><th>Total Attended</th></tr></thead><tbody><tr><td>A</td><td>Algorithms</td><td>L</td><td>20</td><td>18</td></tr><tr><td>A</td><td>Algorithms</td><td>P</td><td>0</td><td>0</td></tr></tbody></table>'''
FILTERS = '''<form action="/index.php?r=student%2Fattendance" method="get"><select name="Attendance[academicyear]"><option value="">Select</option><option value="26">2026-2027</option></select><select name="Attendance[semesterid]"><option value="1">Odd Sem</option></select></form>'''
FILTERS_WITH_SEARCH = FILTERS.replace('</form>', '<button name="yt0" type="submit" value="Search">Search</button></form>')

def test_login_fields_and_csrf():
    action, hidden, image = erp.login_form(LOGIN)
    assert action.endswith('site%2Flogin') and hidden == {'_csrf':'csrf'}
    assert image == erp.ORIGIN + '/captcha'
    with pytest.raises(erp.ERPError): erp.login_form('<html>changed</html>')


def test_login_without_form_id_and_lazy_captcha():
    html = LOGIN.replace('id="login-form"', '').replace(
        'id="loginFormCaptcha-image" src="/captcha"', 'data-src="/captcha"')
    action, hidden, url = erp.login_form(html)
    assert 'site%2Flogin' in action
    assert hidden == {'_csrf': 'csrf'}
    assert url == erp.ORIGIN + '/captcha'


@pytest.mark.parametrize('mime,data', [
    ('text/html', b'<html>temporarily unavailable</html>'),
    ('image/png', b'not an image'),
    ('image/png', b''),
    ('image/svg+xml', b'<svg></svg>'),
])
def test_invalid_captcha_response_is_rejected(mime, data):
    response = httpx.Response(200, content=data, headers={'content-type': mime})
    with pytest.raises(erp.ERPError, match='invalid CAPTCHA'):
        erp.captcha_image(response)
    assert erp.captcha_image(httpx.Response(
        200, content=PNG, headers={'content-type': 'image/png'})) == PNG


@pytest.mark.parametrize('url',['https://evil.test/','//evil.test/x','http://newerp.kluniversity.in','https://newerp.kluniversity.in.evil.test/','https://user@newerp.kluniversity.in/'])
def test_destination_guard(url):
    with pytest.raises(erp.ERPError): erp.safe_url(url)

def test_separate_components_and_zero():
    rows = erp.parse_attendance(TABLE)
    assert len(rows) == 2 and rows[0]['percentage'] == 90
    assert rows[1]['component'] == 'P' and rows[1]['percentage'] is None

def test_fail_closed_on_bad_counts_or_layout():
    for html in [TABLE.replace('<td>18</td>','<td>30</td>'),TABLE.replace('<td>18</td>','<td>unknown</td>'),'<html>login again</html>', '<ul class="pagination"><li class="next"><a href="/next">Next</a></li></ul>'+TABLE]:
        with pytest.raises(erp.ERPError): erp.parse_attendance(html)

def test_filter_values_not_labels():
    result = erp.attendance_form(FILTERS,erp.ORIGIN+'/')
    assert result['years'] == [{'value':'26','label':'2026-2027'}]
    assert result['semester_name'] == 'Attendance[semesterid]'

def test_auth_requires_positive_evidence():
    assert not erp.authenticated('<h1>Server error</h1>')
    assert erp.authenticated('<a href="/index.php?r=site%2Flogout">Logout</a>')
    assert not erp.authenticated(LOGIN)

def test_route_query_preserved():
    async def run():
        async def handler(req):
            assert req.url.params['r']=='student/attendance'
            assert req.url.params['year']=='26'
            return httpx.Response(200,text='ok')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await erp.request(client,'GET','/index.php?r=student%2Fattendance',params={'year':'26'})
    asyncio.run(run())

def test_cross_origin_redirect_blocked():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'location':'https://evil.test'}))) as client:
            with pytest.raises(erp.ERPError): await erp.request(client,'GET','/')
    asyncio.run(run())

def test_api_flow_and_session_isolation(monkeypatch):
    async def fake(client,method,path,**kwargs):
        if path=='/': text=LOGIN
        elif path.endswith('/captcha'): return httpx.Response(200,content=PNG,headers={'content-type':'image/png'})
        elif 'get-stakeholder-id' in path: text='-2'
        elif 'site%2Flogin' in path:
            assert kwargs['data']['LoginForm[password]']=='test-only-password'
            assert kwargs['data']['_csrf']=='csrf'
            assert kwargs['data']['LoginForm[qr_code]']==''
            assert kwargs['headers']['Origin']==erp.ORIGIN
            assert kwargs['headers']['Referer']==erp.ORIGIN+'/'
            text='<a href="/logout">Logout</a><a href="/attendance">Attendance Register</a>'
        elif path.endswith('/attendance'): text=FILTERS
        else:
            assert kwargs['params']['Attendance[academicyear]']=='26'
            text=TABLE
        return httpx.Response(200,text=text,request=httpx.Request(method,erp.ORIGIN+'/attendance'))
    monkeypatch.setattr(erp,'request',fake)
    main.rates.clear()
    with TestClient(main.app) as c:
        first=c.post('/api/challenge')
        assert first.status_code == 200
        assert base64.b64decode(first.json()['captcha']) == PNG
        assert first.headers['cache-control'] == 'no-store'
        a=first.json()['token']; b=c.post('/api/challenge').json()['token']
        headers={'Authorization':'Bearer '+a}
        assert c.get('/api/filters',headers={'Authorization':'Bearer '+b}).status_code==401
        response=c.post('/api/login',headers=headers,json={'student_id':'123','password':'test-only-password','captcha':'ABCD'})
        assert response.status_code==200
        assert c.get('/api/filters',headers=headers).json()['years'][0]['value']=='26'
        assert c.get('/api/attendance?year=26&semester=1',headers=headers).json()['rows'][0]['attended']==18
        assert c.get('/api/attendance?year=99&semester=1',headers=headers).status_code==400
        assert c.delete('/api/session',headers=headers).status_code==200
        assert c.get('/api/filters',headers=headers).status_code==401
        assert 'test-only-password' not in repr(main.sessions)

def test_validation_does_not_echo_credentials():
    main.rates.clear()
    with TestClient(main.app) as c:
        # Body validation may happen after session dependency; either path must not echo input.
        response=c.post('/api/login',json={'student_id':'bad','password':'SECRET-PASSWORD','captcha':''})
        assert 'SECRET-PASSWORD' not in response.text
        assert response.headers['cache-control']=='no-store'

def test_wrong_login_and_mfa_do_not_authenticate(monkeypatch):
    main.rates.clear()
    async def fake(client,method,path,**kwargs):
        if 'get-stakeholder-id' in path:
            text = '1' if kwargs['data']['username']=='999' else '-2'
        else:
            text = LOGIN
        return httpx.Response(200,text=text,request=httpx.Request(method,erp.ORIGIN+'/'))
    monkeypatch.setattr(erp,'request',fake)
    with TestClient(main.app) as c:
        session=main.Session(httpx.AsyncClient(trust_env=False),action=erp.ORIGIN+'/login',hidden={'_csrf':'csrf'})
        main.sessions['test-token']=session
        headers={'Authorization':'Bearer test-token'}
        for student_id,status in [('123',401),('999',403)]:
            r=c.post('/api/login',headers=headers,json={'student_id':student_id,'password':'secret-value','captcha':'wrong'})
            assert r.status_code==status and not session.authenticated
            assert 'secret-value' not in r.text
        r=c.post('/api/login',headers=headers,json={'student_id':'bad','password':'secret-value','captcha':'X'})
        assert r.status_code==422 and 'secret-value' not in r.text
        session.created-=main.TTL+1
        assert c.get('/api/filters',headers=headers).status_code==401


def test_optional_stakeholder_lookup_fails_over_to_official_login(monkeypatch):
    """Fallback never invents authentication; official ERP still decides."""
    main.rates.clear()
    posted = []
    async def fake(client, method, path, **kwargs):
        if 'get-stakeholder-id' in path:
            raise httpx.HTTPStatusError(
                'Lookup temporarily unavailable',
                request=httpx.Request('POST', erp.ORIGIN+'/lookup'),
                response=httpx.Response(503),
            )
        if 'site%2Flogin' in path:
            posted.append(kwargs['data'])
            return httpx.Response(200, text=LOGIN)
        if method == 'GET' and path == '/':
            # A failed ERP sign-in still presents the public login screen.
            return httpx.Response(200, text=LOGIN)
        raise AssertionError('Unexpected ERP endpoint')
    monkeypatch.setattr(erp, 'request', fake)
    with TestClient(main.app) as c:
        main.sessions['fallback-test'] = main.Session(
            httpx.AsyncClient(), action=erp.ORIGIN+'/index.php?r=site%2Flogin',
            hidden={'_csrf': 'fixture-csrf'},
        )
        result = c.post('/api/login',
                        headers={'Authorization': 'Bearer fallback-test'},
                        json={'student_id': '123', 'password': 'private-password',
                              'captcha': 'human-entered-code'})
        assert result.status_code == 401
        assert len(posted) == 1
        assert posted[0]['LoginForm[captcha]'] == 'human-entered-code'
        assert posted[0]['LoginForm[qr_code]'] == ''
        assert not main.sessions['fallback-test'].authenticated
        assert 'private-password' not in result.text


def test_upstream_login_http_error_identifies_stage_but_hides_secrets(monkeypatch):
    main.rates.clear()
    async def fake(client, method, path, **kwargs):
        if 'get-stakeholder-id' in path:
            return httpx.Response(200, text='-2')
        raise httpx.HTTPStatusError(
            'Forbidden upstream',
            request=httpx.Request('POST', erp.ORIGIN+'/login'),
            response=httpx.Response(403),
        )
    monkeypatch.setattr(erp, 'request', fake)
    with TestClient(main.app) as c:
        main.sessions['error-test'] = main.Session(
            httpx.AsyncClient(), action=erp.ORIGIN+'/login',
            hidden={'_csrf': 'fixture-csrf'},
        )
        result = c.post('/api/login',
                        headers={'Authorization': 'Bearer error-test'},
                        json={'student_id': '123', 'password': 'private-password',
                              'captcha': 'test-code'})
        assert result.status_code == 502
        assert 'HTTP 403 Forbidden' in result.text
        assert 'official ERP' in result.text
        assert 'private-password' not in result.text
        assert not main.sessions['error-test'].authenticated


def test_upstream_mfa_and_rate_limit_do_not_submit_password(monkeypatch):
    main.rates.clear()
    for response_code, status in [(1, 403), (429, 429)]:
        post_calls = []
        async def fake(client, method, path, **kwargs):
            if 'get-stakeholder-id' in path:
                if response_code == 1:
                    return httpx.Response(200, text='1')
                raise httpx.HTTPStatusError(
                    'Rate limited',
                    request=httpx.Request('POST', erp.ORIGIN+'/lookup'),
                    response=httpx.Response(429),
                )
            post_calls.append(path)
            raise AssertionError('Login submission must be blocked')
        monkeypatch.setattr(erp, 'request', fake)
        token = 'blocked-' + str(response_code)
        with TestClient(main.app) as c:
            main.sessions[token] = main.Session(
                httpx.AsyncClient(), action=erp.ORIGIN+'/login',
                hidden={'_csrf': 'fixture-csrf'},
            )
            result = c.post('/api/login',
                            headers={'Authorization': 'Bearer ' + token},
                            json={'student_id': '123', 'password': 'private-password',
                                  'captcha': 'test-code'})
            assert result.status_code == status
            assert not post_calls
            assert not main.sessions[token].authenticated


def test_safe_login_failure_classification():
    captcha = LOGIN.replace(
        '<img id="loginFormCaptcha-image"',
        '<div id="field-loginform-captcha" class="has-error">'
        '<div class="help-block">Some untrusted upstream text 123</div></div>'
        '<img id="loginFormCaptcha-image"')
    credentials = LOGIN.replace(
        '<img id="loginFormCaptcha-image"',
        '<div id="field-loginform-password" class="has-error"></div>'
        '<img id="loginFormCaptcha-image"')
    assert erp.login_failure_reason(captcha) == 'captcha'
    assert erp.login_failure_reason(credentials) == 'credentials'
    assert erp.login_failure_reason(LOGIN) == 'unconfirmed'
    assert erp.login_failure_reason('<h1>Temporary upstream issue</h1>') == 'unconfirmed'
    assert not erp.authenticated(LOGIN + '<form action="/site/logout"></form>')
    assert erp.authenticated('<form action="/index.php?r=site%2Flogout"></form>')
    assert 'untrusted' not in str(erp.login_failure_reason(captcha))


@pytest.mark.parametrize('kind,message', [
    ('captcha', 'ERP rejected the CAPTCHA'),
    ('password', 'ERP did not accept the sign-in details'),
])
def test_server_side_login_field_errors_are_not_echoed(monkeypatch, kind, message):
    main.rates.clear()
    details = {
        'captcha': '<div id="field-loginform-captcha" class="has-error">private error</div>',
        'password': '<div id="field-loginform-password" class="has-error">private error</div>',
    }
    seen_paths = []
    async def fake(client, method, path, **kwargs):
        seen_paths.append((method, path))
        if 'get-stakeholder-id' in path:
            return httpx.Response(200, text='-2')
        if 'site%2Flogin' in path:
            return httpx.Response(200, text=LOGIN + details[kind])
        raise AssertionError('No GET recheck is needed for a recognized login error')
    monkeypatch.setattr(erp, 'request', fake)
    with TestClient(main.app) as c:
        token='field-error-' + kind
        main.sessions[token]=main.Session(httpx.AsyncClient(), action=erp.ORIGIN+'/index.php?r=site%2Flogin', hidden={'_csrf': 'fixture'})
        r=c.post('/api/login', headers={'Authorization':'Bearer '+token},
                 json={'student_id':'123','password':'secret-password','captcha':'wrong-code'})
        assert r.status_code == 401
        assert message in r.text
        assert 'private error' not in r.text
        assert 'secret-password' not in r.text
        assert not main.sessions[token].authenticated
        assert not any(method=='GET' for method, path in seen_paths)


def test_login_intermediate_page_uses_one_safe_get_confirmation(monkeypatch):
    main.rates.clear()
    requests = []
    async def fake(client, method, path, **kwargs):
        requests.append((method, path))
        if 'get-stakeholder-id' in path:
            return httpx.Response(200, text='-2')
        if method == 'POST':
            return httpx.Response(200, text='<h1>Continuing session</h1>')
        if method == 'GET' and path == '/':
            return httpx.Response(200, text='<form action="/site/logout"></form><a href="/attendance">Attendance Register</a>')
        raise AssertionError('Unexpected request')
    monkeypatch.setattr(erp, 'request', fake)
    with TestClient(main.app) as c:
        main.sessions['intermediate-test'] = main.Session(httpx.AsyncClient(), action=erp.ORIGIN+'/login',hidden={'_csrf':'fixture'})
        r=c.post('/api/login',headers={'Authorization':'Bearer intermediate-test'},json={'student_id':'123','password':'sample-password','captcha':'human-code'})
        assert r.status_code==200
        assert r.json()['authenticated']
        assert len([q for q in requests if q[0] == 'POST' and 'get-stakeholder-id' not in q[1]])==1
        assert len([q for q in requests if q[0] == 'GET'])==1


def test_unknown_login_response_never_creates_session(monkeypatch):
    main.rates.clear()
    async def fake(client, method, path, **kwargs):
        if 'get-stakeholder-id' in path:
            return httpx.Response(200,text='-2')
        return httpx.Response(200,text=LOGIN if method=='GET' else '<h1>Unknown response</h1>')
    monkeypatch.setattr(erp,'request',fake)
    with TestClient(main.app) as c:
        main.sessions['no-evidence'] = main.Session(httpx.AsyncClient(), action=erp.ORIGIN+'/login',hidden={'_csrf':'fixture'})
        r=c.post('/api/login',headers={'Authorization':'Bearer no-evidence'},json={'student_id':'123','password':'secret-value','captcha':'human-code'})
        assert r.status_code==401
        assert 'does not necessarily mean your password is wrong' in r.text
        assert not main.sessions['no-evidence'].authenticated
        assert 'secret-value' not in r.text


def test_attendance_submitter_is_included_only_when_known_search_action():
    result = erp.attendance_form(FILTERS_WITH_SEARCH, erp.ORIGIN + '/index.php')
    assert result['submit'] == {'yt0': 'Search'}
    assert result['referer'].startswith('https://newerp.kluniversity.in/')
    assert erp.attendance_form(FILTERS, erp.ORIGIN + '/')['submit'] == {}
    malicious = FILTERS.replace(
        '</form>', '<button type="submit" name="danger" value="Delete">Delete</button></form>')
    assert erp.attendance_form(malicious, erp.ORIGIN + '/')['submit'] == {}


def test_missing_results_are_not_misrepresented_as_zero_attendance():
    with pytest.raises(erp.ERPError, match='returned attendance filters'):
        erp.parse_attendance(FILTERS)
    with pytest.raises(erp.ERPError, match='unfamiliar attendance columns'):
        erp.parse_attendance('<table><tr><th>Student</th><th>Grades</th></tr><tr><td>A</td><td>B</td></tr></table>')


def test_gateway_sends_search_button_to_erp(monkeypatch):
    main.rates.clear()
    calls = []
    async def fake(client, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if 'attendance' in path and 'params' not in kwargs:
            return httpx.Response(200, text=FILTERS_WITH_SEARCH,
                                  request=httpx.Request('GET', erp.safe_url(path)))
        if 'attendance' in path and 'params' in kwargs:
            assert kwargs['params']['yt0'] == 'Search'
            assert kwargs['params']['Attendance[academicyear]'] == '26'
            assert kwargs['params']['Attendance[semesterid]'] == '1'
            assert kwargs['headers']['Referer'].startswith(erp.ORIGIN)
            return httpx.Response(200, text=TABLE,
                                  request=httpx.Request('GET', erp.safe_url(path)))
        raise AssertionError('unexpected mocked route')
    monkeypatch.setattr(erp, 'request', fake)
    with TestClient(main.app) as client:
        main.sessions['search-test'] = main.Session(
            httpx.AsyncClient(), action=erp.ORIGIN+'/login', authenticated=True,
            page='<a href="/attendance">Attendance Register</a>',
        )
        r=client.get('/api/attendance?year=26&semester=1',
                     headers={'Authorization':'Bearer search-test'})
        assert r.status_code == 200, r.text
        assert r.json()['rows'][0]['attended'] == 18
        assert len(calls) == 2

import asyncio
import pytest
import httpx
from fastapi.testclient import TestClient
from backend import erp, main

LOGIN = '''<form id="login-form" action="/index.php?r=site%2Flogin"><input type="hidden" name="_csrf" value="csrf"><input name="LoginForm[username]"><input name="LoginForm[password]"><input name="LoginForm[captcha]"><img id="loginFormCaptcha-image" src="/captcha"></form>'''
TABLE = '''<table><thead><tr><th>Coursecode</th><th>Coursedesc</th><th>Ltps</th><th>Total Conducted</th><th>Total Attended</th></tr></thead><tbody><tr><td>A</td><td>Algorithms</td><td>L</td><td>20</td><td>18</td></tr><tr><td>A</td><td>Algorithms</td><td>P</td><td>0</td><td>0</td></tr></tbody></table>'''
FILTERS = '''<form action="/index.php?r=student%2Fattendance" method="get"><select name="Attendance[academicyear]"><option value="">Select</option><option value="26">2026-2027</option></select><select name="Attendance[semesterid]"><option value="1">Odd Sem</option></select></form>'''

def test_login_fields_and_csrf():
    action, hidden, image = erp.login_form(LOGIN)
    assert action.endswith('site%2Flogin') and hidden == {'_csrf':'csrf'}
    assert image == erp.ORIGIN + '/captcha'
    with pytest.raises(erp.ERPError): erp.login_form('<html>changed</html>')

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
        elif path.endswith('/captcha'): return httpx.Response(200,content=b'image',headers={'content-type':'image/png'})
        elif 'get-stakeholder-id' in path: text='-2'
        elif 'site%2Flogin' in path:
            assert kwargs['data']['LoginForm[password]']=='test-only-password'
            assert kwargs['data']['_csrf']=='csrf'
            text='<a href="/logout">Logout</a><a href="/attendance">Attendance Register</a>'
        elif path.endswith('/attendance'): text=FILTERS
        else:
            assert kwargs['params']['Attendance[academicyear]']=='26'
            text=TABLE
        return httpx.Response(200,text=text,request=httpx.Request(method,erp.ORIGIN+'/attendance'))
    monkeypatch.setattr(erp,'request',fake)
    main.rates.clear()
    with TestClient(main.app) as c:
        a=c.post('/api/challenge').json()['token']; b=c.post('/api/challenge').json()['token']
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

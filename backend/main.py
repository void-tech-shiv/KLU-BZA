import asyncio
import base64
import os
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr
import httpx
from . import erp

TTL = 20 * 60
sessions = {}
rates = {}
@dataclass
class Session:
    client: httpx.AsyncClient
    created: float = field(default_factory=time.monotonic)
    action: str = ''
    hidden: dict = field(default_factory=dict)
    page: str = ''
    authenticated: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

async def cleanup():
    while True:
        await asyncio.sleep(30)
        for token, session in list(sessions.items()):
            if time.monotonic() - session.created > TTL:
                sessions.pop(token, None)
                async with session.lock:
                    await session.client.aclose()
        now = time.monotonic()
        for ip, hits in list(rates.items()):
            if not hits or now - hits[-1] > 60:
                rates.pop(ip, None)

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(cleanup())
    yield
    task.cancel()
    for session in sessions.values():
        await session.client.aclose()
    sessions.clear()

app = FastAPI(title='KLU BZA student gateway', lifespan=lifespan, docs_url=None, redoc_url=None)
origins = [o.strip() for o in os.getenv('APP_ORIGINS', 'http://localhost:8080').split(',') if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET','POST','DELETE'],
                   allow_headers=['Authorization', 'Content-Type'])

@app.middleware('http')
async def safeguards(request: Request, call_next):
    if request.method != 'OPTIONS':
        ip = request.client.host if request.client else 'unknown'
        now = time.monotonic()
        hits = [t for t in rates.get(ip, []) if now - t < 60]
        if len(hits) >= 30 or (ip not in rates and len(rates) >= 10000):
            return JSONResponse({'detail': 'Too many requests. Wait one minute.'}, status_code=429)
        rates[ip] = hits + [now]
        body = await request.body()
        if len(body) > 8192:
            return JSONResponse({'detail': 'Request too large.'}, status_code=413)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.exception_handler(erp.ERPError)
async def erp_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=502)

@app.exception_handler(httpx.HTTPError)
async def upstream_error(request, exc):
    return JSONResponse({'detail': 'ERP could not be reached. Please retry later.'}, status_code=502)

# Override validation responses: never echo password, token or submitted request data.
from fastapi.exceptions import RequestValidationError
@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({'detail': 'Check the required fields and their lengths.'}, status_code=422)

def get_session(request: Request):
    token = request.headers.get('authorization', '').removeprefix('Bearer ')
    session = sessions.get(token)
    if not session or time.monotonic() - session.created > TTL:
        raise HTTPException(401, 'Session expired. Please sign in again.')
    return session

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/api/challenge')
async def challenge():
    if len(sessions) >= 200:
        raise HTTPException(503, 'Server is busy. Please try later.')
    client = httpx.AsyncClient(timeout=25, follow_redirects=False, headers={'User-Agent': 'KLU-BZA/0.1 StudentClient'})
    try:
        r = await erp.request(client, 'GET', '/')
        action, hidden, image_url = erp.login_form(r.text)
        img = await erp.request(
            client, 'GET', image_url,
            headers={'Referer': str(r.url), 'Accept': 'image/png,image/jpeg,image/gif,image/webp,*/*;q=0.8',
                     'Cache-Control': 'no-cache'},
        )
        captcha_bytes = erp.captcha_image(img)
        token = secrets.token_urlsafe(32)
        sessions[token] = Session(client, action=action, hidden=hidden)
        return {'token': token, 'captcha': base64.b64encode(captcha_bytes).decode(), 'expires_in': TTL}
    except Exception:
        await client.aclose()
        raise

class Login(BaseModel):
    student_id: str = Field(min_length=1, max_length=64, pattern=r'^\d+$')
    password: SecretStr = Field(min_length=1, max_length=256)
    captcha: str = Field(min_length=1, max_length=32)

@app.post('/api/login')
async def login(data: Login, session: Session = Depends(get_session)):
    async with session.lock:
        if session.authenticated:
            raise HTTPException(409, 'Already signed in.')
        # Stakeholder lookup controls the optional MFA UI on the public ERP form.
        # A missing/unavailable lookup must not prevent a NORMAL form submission:
        # ERP itself still validates password, CAPTCHA and any required MFA.
        # A positive MFA response, rate limit, or unexpected response fails closed.
        try:
            check = await erp.request(
                session.client, 'POST', '/index.php?r=site%2Fget-stakeholder-id',
                data={**session.hidden, 'username': data.student_id},
                headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': erp.ORIGIN + '/'},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (404, 405, 500, 502, 503, 504):
                if exc.response.status_code == 429:
                    raise HTTPException(429, 'ERP temporarily rate-limited login. Retry later.')
                raise HTTPException(502,
                    f'ERP account check returned HTTP {exc.response.status_code}; use the official ERP.')
        except httpx.TransportError:
            # The optional AJAX lookup is unreachable; attempt the official login
            # form exactly once. Never retry a password POST automatically.
            pass
        else:
            if check.text.strip() == '1':
                raise HTTPException(403, 'This account requires MFA. Please use the official ERP.')
            if check.text.strip() not in ('-2', '-1', '-3'):
                raise erp.ERPError('ERP account check returned an unexpected response. Use the official ERP.')
        try:
            r = await erp.request(
                session.client, 'POST', session.action,
                data={**session.hidden,
                      'LoginForm[username]': data.student_id,
                      'LoginForm[password]': data.password.get_secret_value(),
                      'LoginForm[captcha]': data.captcha,
                      # Present even when empty in the university's public HTML form.
                      'LoginForm[qr_code]': '',
                      'login-button': ''},
                headers={
                    # Match ordinary browser form semantics for origin/CSRF checks.
                    # Never skip the ERP's own CAPTCHA or access restrictions.
                    'Origin': erp.ORIGIN,
                    'Referer': erp.ORIGIN + '/',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                raise HTTPException(
                    502, 'ERP rejected the login request (HTTP 403 Forbidden). '
                         'This may be a session/CSRF issue or a university-side access restriction. '
                         'Use the official ERP in your browser rather than repeatedly retrying.')
            raise HTTPException(
                502, f'ERP login returned HTTP {exc.response.status_code}. '
                     'Use the official ERP if the problem persists.')
        except httpx.TransportError:
            raise HTTPException(
                502, 'ERP login connection timed out or failed. '
                     'Try again later with a new CAPTCHA.')

        if not erp.authenticated(r.text):
            raise HTTPException(401, 'Login unsuccessful. Check your details and load a new CAPTCHA.')
        session.authenticated = True
        session.page = r.text
        return {'authenticated': True}

async def filters(session):
    if not session.authenticated:
        raise HTTPException(401, 'Please sign in first.')
    path = os.getenv('ERP_ATTENDANCE_PATH') or erp.attendance_link(session.page)
    r = await erp.request(session.client, 'GET', path)
    if erp.soup(r.text).select_one('form#login-form'):
        session.authenticated = False
        raise HTTPException(401, 'ERP session expired. Please sign in again.')
    return erp.attendance_form(r.text, str(r.url))

@app.get('/api/filters')
async def get_filters(session: Session = Depends(get_session)):
    async with session.lock:
        f = await filters(session)
        return {k: f[k] for k in ('years','semesters')}

@app.get('/api/attendance')
async def attendance(year: str, semester: str, session: Session = Depends(get_session)):
    async with session.lock:
        f = await filters(session)
        if year not in [x['value'] for x in f['years']] or semester not in [x['value'] for x in f['semesters']]:
            raise HTTPException(400, 'Select an available academic year and semester.')
        payload = {**f['hidden'], f['year_name']: year, f['semester_name']: semester}
        if f['method'] not in ('GET','POST'):
            raise erp.ERPError('Unexpected attendance form method.')
        r = await erp.request(session.client, f['method'], f['url'],
                              **({'params': payload} if f['method'] == 'GET' else {'data': payload}))
        if erp.soup(r.text).select_one('form#login-form'):
            session.authenticated = False
            raise HTTPException(401, 'ERP session expired. Please sign in again.')
        return {'rows': erp.parse_attendance(r.text), 'synced_at': datetime.now(timezone.utc).isoformat()}

@app.delete('/api/session')
async def logout(request: Request):
    token = request.headers.get('authorization', '').removeprefix('Bearer ')
    session = sessions.pop(token, None)
    if session:
        async with session.lock:
            await session.client.aclose()
    return {'logged_out': True}

# KLU BZA

Unofficial student attendance companion for KL University Vijayawada. One Flutter application targets **Android and web**, backed by a Python FastAPI ERP adapter.

## What is implemented

- Student ID, password and human-entered ERP CAPTCHA; no MFA field. Accounts for which ERP requires MFA are directed to the official ERP.
- Fresh per-user HTTP cookie jars, CSRF forwarding, CAPTCHA fetch (automatically on launch with a configured gateway), student MFA lookup and login submission based on the observed public ERP form.
- CAPTCHA refresh survives an expired prior session; invalid upstream CAPTCHA responses are rejected rather than displayed as broken images.
- Semantic attendance parser, academic-year and semester filters, separate L/P/S component cards, selectable attendance target and catch-up/miss calculations.
- Responsive layout, explicit fictional demo, empty/error/loading states, sign-out and last successful sync time. Data remains visible during a failed refresh, but is cleared on logout or filter change.
- Backend tests and CI that builds a web bundle and a **debug APK**.

## Verification boundary

**This is an integration preview, not a verified production student service.** Public login markup was inspected on 24 October 2026. No real student credentials were used. Login success, authenticated menu discovery, actual attendance form names/options, pagination, and session expiry still require an account-owner test. The attendance adapter infers forms from semantic field names and table headings; it fails with a visible error rather than fabricating results. Screenshots alone do not establish the authenticated HTML contract.

The demo uses invented records. No supplied screenshot, student ID, password, cookies or real attendance records are committed. Timetable, marks, fees, notifications and durable offline storage are not implemented in this version.

## Live free cloud gateway (Render)

The student API is deployed to the **Free** Render plan in Singapore:

- **HTTPS API:** https://klu-bza-student-gateway.onrender.com
- **Health check:** https://klu-bza-student-gateway.onrender.com/health
- **Dashboard:** https://dashboard.render.com/web/srv-dbe6ejgm7kps73cq4q5g
- **Deploy branch:** `fix/erp-captcha-autoload` until integration checks have passed.

GitHub Actions uses this public API URL by default when the repository Actions variable `API_BASE_URL` is empty. Both the downloadable debug APK and downloadable web bundle are therefore **live-configured**, not demo-only. When changing the API host, update the variable and rebuild. Never set it to a URL without HTTPS.

The gateway is an **unofficial student integration preview**. Do not submit university credentials until the service owner has personally checked the upstream login/CAPTCHA flow, hosting/log retention, and KL University's integration rules. Never submit passwords in GitHub issues or chat. No account passwords or CAPTCHA responses are stored by the app; the gateway handles credentials transiently while proxying to ERP.

Render's Free services can spin down after 15 minutes of inactivity; a cold start may take around a minute. Because session cookies are in the backend's process memory, any spin-down/redeploy requires the student to obtain a new CAPTCHA and sign in again. Do not treat this free test gateway as a highly available production service. The free plan has monthly resource limits.

## Run locally

Requirements: Python 3.12+, Flutter stable SDK, and Android Studio/Android SDK for APKs. Run `flutter doctor` and resolve Android toolchain requirements first. Java 17 is used by CI.

From the repository root:

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

In a second terminal, from the repository root:

```sh
python scripts/bootstrap.py
cd client
flutter pub get
flutter run -d chrome --web-port 8080 --dart-define=API_BASE_URL=http://localhost:8000
```

The bootstrap creates Android/web platform files, grants Android Internet permission and disables cleartext Android network traffic and application backup. Run it before opening `client/android` in Android Studio. Application source is in `client/lib`.

For Android, use an **HTTPS gateway reachable from the phone**:

```sh
flutter run --dart-define=API_BASE_URL=https://YOUR-GATEWAY-HOST
flutter build apk --debug --dart-define=API_BASE_URL=https://YOUR-GATEWAY-HOST
```

Without `API_BASE_URL`, both builds offer a clearly labelled demo, and live sign-in is disabled. If a live build shows no CAPTCHA, first confirm that the login form is visible and the build used the correct `API_BASE_URL`. The client automatically requests the CAPTCHA on opening the login screen and also provides **New CAPTCHA** for a manual retry. A gateway/API error is shown above the login form; do not try to work around ERP CAPTCHA or MFA. Android localhost refers to the phone, not your laptop. No paid hosting resource is provisioned by this repository.

## GitHub builds

Open **Actions → Test and build Android + web**. A successful run uploads `klu-bza-web` and `klu-bza-android-debug`. Download the Android artifact ZIP and extract `app-debug.apk` to install a test build. Set the repository **Actions variable** `API_BASE_URL` to your HTTPS backend URL and rerun the workflow for live integration testing. The URL is not a secret; never put credentials in build variables.

The web bundle is not automatically hosted. Serve `client/build/web` through HTTPS and add that exact website origin to backend `APP_ORIGINS` (comma separated). The debug APK is for testing, not a Play Store signed release.

## Backend deployment and privacy

`Dockerfile` runs one worker on port 8000. Use HTTPS termination, no request-body/header logging, an 8 KiB ingress body limit, and edge rate limiting. Configure `APP_ORIGINS` to exact web origins. The gateway receives a password transiently to forward it to ERP; choose a trusted host. Passwords are neither logged nor stored by application code. Tokens stay only in Flutter memory; ERP cookies stay only in server memory. Browser reload/app restart requires login. Logout destroys the gateway cookie jar; it does not revoke other ERP sessions.

Sessions expire after 20 minutes, with at most 200 sessions. Rate limits are per connection IP and in memory. **Use one process/instance only** until a shared session store and distributed limiter are designed. Behind a proxy, the conservative per-IP limit may apply to all students together; configure trusted client-IP handling and edge limits before public rollout. Do not turn on arbitrary forwarded-header trust. Memory-only state is lost on server restart. No server-side credential reuse, CAPTCHA solving, or cross-account lookup is implemented.

If the attendance menu is not directly linked from the signed-in landing page, configure `ERP_ATTENDANCE_PATH` with its observed `/index.php?r=...` path. The adapter rejects external origins and redirects. Do not guess a route. For parser adjustments, obtain sanitized form/table HTML: remove student identity, CSRF values, cookies, hidden tokens and personal rows before sharing. Never upload a raw HAR file or credentials.

## Checks

```sh
python -m pytest backend/tests -q
cd client
flutter test
flutter build web
flutter build apk --debug
```

Before sharing with students, verify: fresh CAPTCHA and refresh, valid/invalid credentials, wrong CAPTCHA retry, correct academic year/semester, every L/P/S row against ERP, empty terms, route query preservation, expired session, logout, two separate student sessions, mobile layout and HTTPS/CORS on both platforms. Confirm any pagination before trusting totals. University eligibility may include other rules; the target calculator is only arithmetic using the user's selected target.

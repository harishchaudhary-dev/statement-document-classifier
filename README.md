# Statement Document Classifier

A FastAPI service that authenticates users via Google OAuth, classifies financial statement PDFs with a trained ML model, extracts structured fields, and optionally auto-detects statement attachments from Gmail.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Google OAuth Configuration](#google-oauth-configuration)
- [Running Locally](#running-locally)
- [API Reference](#api-reference)
- [Gmail Auto-Detection](#gmail-auto-detection)
- [Troubleshooting](#troubleshooting)
- [Security Notes](#security-notes)
- [Production Readiness](#production-readiness)
- [License](#license)

---

## Overview

| Capability | Status |
|---|---|
| Google OAuth 2.0 login | ✅ |
| Session-based auth | ✅ |
| PDF upload + classification | ✅ |
| Structured field extraction | ✅ |
| Gmail auto-detection (polling) | ✅ |
| Gmail Pub/Sub webhook | ✅ |
| Health check endpoint | ✅ |
| Swagger/OpenAPI docs | ❌ (intentionally disabled) |
| Persistent storage | ❌ (in-memory only — see [Production Readiness](#production-readiness)) |

---

## Architecture

```text
                         ┌─────────────────────┐
                         │       Browser       │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   FastAPI (app.py)  │
                         └──────────┬──────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             ▼                      ▼                      ▼
      ┌─────────────┐       ┌──────────────┐       ┌──────────────┐
      │ Google OAuth│       │ PDF Processor │       │ Gmail Service│
      └─────────────┘       └───────┬──────┘       └───────┬──────┘
                                     ▼                       ▼
                             ┌──────────────┐         ┌──────────────┐
                             │ ML Classifier│         │  Gmail API   │
                             │  model.pkl   │         └──────────────┘
                             └───────┬──────┘
                                     ▼
                             ┌──────────────┐
                             │  Statement   │
                             │    Parser    │
                             └──────────────┘
```

---

## Project Structure

```text
statement-document-classifier/
│
├── app.py                 # FastAPI app, routes, OAuth callback, lifespan
├── requirements.txt
├── .env                    # local secrets — never commit
├── .env.example             # safe template — commit this
├── .gitignore
├── README.md
│
├── credentials.json         # Gmail OAuth client — never commit
├── token.json                # Gmail OAuth token — never commit
│
├── src/
│   ├── __init__.py
│   ├── classifier.py         # ML model wrapper
│   ├── config.py               # pydantic-settings config
│   ├── extractor.py             # PDF text extraction
│   ├── gmail_service.py          # Gmail API client
│   ├── parser.py                  # Field extraction logic
│   └── model.pkl                   # Trained classifier
│
└── templates/
    ├── login.html
    └── dashboard.html
```

---

## Requirements

- Python 3.11+ (3.12 supported)
- A Google Cloud project with:
  - OAuth 2.0 **Web application** client (for login)
  - Gmail API enabled (for auto-detection, optional)
- `pip install -r requirements.txt`

---

## Setup

```bash
git clone <your-repo-url>
cd statement-document-classifier

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env           # then fill in real values — see below
```

---

## Environment Variables

Create `.env` in the project root. **Every key must appear exactly once.** A duplicated key (e.g. two `GOOGLE_CLIENT_SECRET=` lines) is a silent footgun: `python-dotenv` resolves to whichever occurrence comes last in the file, with no warning, which is a common cause of `invalid_client` errors that otherwise look inexplicable.

```env
PROJECT_NAME=Statement Document Classifier
API_V1_STR=/api/v1

MODEL_PATH=src/model.pkl

GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
AUTO_GMAIL_DETECTION_ENABLED=true
GMAIL_POLL_INTERVAL_SECONDS=60

GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-real-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback

SESSION_SECRET_KEY=a-long-random-string
```

Generate a strong session secret rather than leaving a placeholder:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

| Variable | Required | Notes |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | From Google Cloud Console → Credentials |
| `GOOGLE_CLIENT_SECRET` | Yes | Must belong to the **same** OAuth client as the ID above. Copy it at creation time — Console only shows the full value once. |
| `GOOGLE_REDIRECT_URI` | Yes | Must match an **Authorized redirect URI** in Console, character-for-character |
| `SESSION_SECRET_KEY` | Yes | Random, ≥32 bytes. Rotating it invalidates all active sessions. |
| `AUTO_GMAIL_DETECTION_ENABLED` | No | Set `false` to disable the background Gmail poller |
| `GMAIL_POLL_INTERVAL_SECONDS` | No | Minimum enforced value is 5s |

---

## Google OAuth Configuration

1. In [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials), create (or open) an OAuth 2.0 **Web application** client.
2. **Authorized redirect URIs** must contain exactly:
   ```
   http://127.0.0.1:8000/auth/google/callback
   ```
3. **Authorized JavaScript origins** should include:
   ```
   http://127.0.0.1:8000
   ```
4. `127.0.0.1` and `localhost` are treated as **different origins** by Google — don't mix them between Console and your `.env`.
5. Under **Client secrets**, click **Add secret** to generate a new one. Copy the full value immediately; the masked value shown afterward (`****xxxx`) cannot be recovered.
6. If your app is in **Testing** publishing status, add your Google account under **Test users**, or the consent screen will block login entirely.

**Client ID and Client Secret must belong to the same OAuth client.** Mixing credentials from two different clients is a common cause of `invalid_client` and is easy to do by accident when a project has multiple OAuth clients.

---

## Running Locally

```bash
python app.py
# or
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

| URL | Purpose |
|---|---|
| `http://127.0.0.1:8000/` | Login page |
| `http://127.0.0.1:8000/auth/login` | Starts Google OAuth |
| `http://127.0.0.1:8000/dashboard` | Protected dashboard |
| `http://127.0.0.1:8000/health` | Health check |

> `reload=True` restarts the worker process on file changes, but `pydantic-settings` reads `.env` at import time. After editing `.env`, do a **full stop/restart** (not just save-triggered reload) to guarantee the new values are picked up.

---

## API Reference

### `GET /`
Login page. Redirects to `/dashboard` if already authenticated.

### `GET /auth/login`
Redirects to Google's consent screen.

### `GET /auth/google/callback`
Google's OAuth redirect target. Exchanges the auth code for a token, stores the user in session, redirects to `/dashboard`. On failure, redirects to `/?error=google_login_failed&reason=<ExceptionType>`.

### `GET /dashboard`
Protected. Requires an authenticated session.

### `GET /auth/logout`
Clears the session.

### `POST /api/v1/classify-statement`
Auth required. Accepts a PDF upload, returns classification + extracted fields.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/classify-statement \
  -H "Cookie: statement_classifier_session=<your-session-cookie>" \
  -F "file=@statement.pdf"
```

### `GET /api/v1/processed-statements`
Auth required. Returns statements captured via Gmail auto-detection.

### `POST /api/v1/gmail-webhook`
Gmail Pub/Sub push endpoint. **Production deployments must verify the Pub/Sub request** (e.g. JWT audience/issuer checks) before trusting the payload — this is not implemented by default.

### `GET /health`
```json
{
  "status": "healthy",
  "gmail_authenticated": true,
  "gmail_auto_detection": true,
  "processed_statements": 0
}
```

---

## Gmail Auto-Detection

When `AUTO_GMAIL_DETECTION_ENABLED=true`, a background task polls Gmail on `GMAIL_POLL_INTERVAL_SECONDS`:

```text
Check Gmail → find unread statement PDFs → download → classify →
extract fields → store result → mark message as read → wait → repeat
```

Messages are marked read **only after successful processing**, so a crash mid-pipeline leaves the message unread for retry on the next poll.

This requires a separate Gmail OAuth credential (`credentials.json` / `token.json`) — it is **independent of the website login flow** and can fail without affecting user login.

---

## Troubleshooting

### `invalid_client: The provided client secret is invalid`

Google rejected the client credentials during token exchange (`POST https://oauth2.googleapis.com/token` → `401`). Check in order:

1. **Duplicate keys in `.env`.** Search the file for `GOOGLE_CLIENT_SECRET` — it must appear exactly once. A second occurrence silently overrides the first with no error.
2. **Placeholder text left in place** (e.g. `YOUR_CLIENT_SECRET_HERE`) instead of a real value.
3. **Client ID / secret mismatch** — verify both belong to the same OAuth client in Console.
4. **Masked value copied instead of the real one** — `****xxxx` shown in Console after the fact is not usable; generate a new secret to get the full value.
5. **Stale process** — config is loaded at import time; fully restart after editing `.env`.
6. **Config not loading at all** — verify by temporarily logging `len(settings.GOOGLE_CLIENT_SECRET)` at startup. `0` means `.env` isn't being found; check `BASE_DIR` resolution in `src/config.py` and your working directory.

### `/?error=google_login_failed&reason=<ExceptionType>`

This is your app's own redirect after catching an exception in `/auth/google/callback` — **not** the root cause. The real error is in the server log immediately above, via `logger.exception(...)`. Fix that underlying error; this redirect will stop firing on its own.

### `Access blocked: Authorization Error` (shown by Google, not your app)

Check in Console:
- Client type is **Web application**
- Redirect URI matches exactly
- OAuth consent screen is configured
- Your account is added as a **test user** if the app is in Testing mode
- Required APIs (Gmail API, if used) are enabled
- You're editing the client under the correct GCP project

### `Gmail API service is not authenticated. Skipping Gmail polling.`

Gmail auto-detection is unavailable — **this is unrelated to website login.** Check that `credentials.json` and `token.json` exist and are valid, and that Gmail OAuth has been completed separately.

### `Gmail OAuth credentials file was not found: credentials.json`

`GMAIL_CREDENTIALS_FILE` doesn't resolve to an existing file. Confirm the path in `.env` and that `credentials.json` sits at the location `src/config.py` expects.

---

## Security Notes

Never commit:

```text
.env
credentials.json
token.json
```

`.gitignore`:

```gitignore
.env
.env.*
!.env.example

credentials.json
token.json

__pycache__/
*.py[cod]
*.pyo

.venv/
venv/
env/

.vscode/
.idea/

.DS_Store
Thumbs.db

*.log

.pytest_cache/
.mypy_cache/
.ruff_cache/
```

**If a client secret, session key, or Gmail credential has ever been committed or pasted anywhere public (GitHub, a chat log, a screenshot), treat it as compromised and rotate it in Google Cloud Console immediately** — masking a value in a screenshot after the fact does not un-expose it if the raw value was visible at any point.

---

## Production Readiness

The current implementation uses in-memory storage (`PROCESSED_STATEMENTS_STORE`) — fine for local development, not for production. Before exposing this publicly:

- [ ] Replace in-memory store with PostgreSQL (users, statements, Gmail messages, processing status)
- [ ] Add Redis for background jobs / caching if polling scales up
- [ ] Serve behind HTTPS; set `https_only=True` on `SessionMiddleware`
- [ ] Verify Gmail Pub/Sub webhook requests (JWT validation) before processing
- [ ] Add request size limits and PDF validation (magic bytes, not just extension)
- [ ] Add rate limiting on public endpoints
- [ ] Add structured logging + error monitoring (e.g. Sentry)
- [ ] Move secrets to a secrets manager rather than a flat `.env`
- [ ] Add CSRF protection where applicable
- [ ] Add proper authorization rules beyond "session exists"
- [ ] Rotate OAuth credentials on a defined schedule

---

## License

Add your intended license here, e.g.:

```text
MIT License
```

# Statement Document Classifier

A FastAPI-based application that authenticates users with Google OAuth, processes financial statement PDFs, classifies documents using a trained machine-learning model, extracts structured information, and optionally monitors Gmail for statement PDF attachments.

## Features

* Google OAuth 2.0 authentication
* Protected dashboard
* PDF statement upload
* Machine-learning document classification
* Structured statement field extraction
* Gmail statement auto-detection
* Gmail PDF attachment processing
* Background Gmail polling
* Gmail Pub/Sub webhook endpoint
* Session-based authentication
* Health-check endpoint
* FastAPI Swagger/OpenAPI documentation disabled
* Configurable environment variables
* Local development support

---

## Application Architecture

```text
                         ┌─────────────────────┐
                         │       Browser       │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │      FastAPI        │
                         │      app.py         │
                         └──────────┬──────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             │                      │                      │
             ▼                      ▼                      ▼
      ┌─────────────┐       ┌──────────────┐       ┌──────────────┐
      │ Google OAuth│       │ PDF Processor │       │ Gmail Service│
      └─────────────┘       └───────┬──────┘       └───────┬──────┘
                                    │                        │
                                    ▼                        ▼
                            ┌──────────────┐          ┌──────────────┐
                            │ ML Classifier│          │ Gmail API    │
                            │  model.pkl   │          └──────────────┘
                            └───────┬──────┘
                                    │
                                    ▼
                            ┌──────────────┐
                            │Statement     │
                            │Parser        │
                            └──────────────┘
```

---

# Project Structure

```text
statement-document-classifier/
│
├── app.py
├── requirements.txt
├── .env
├── .env.example
├── .gitignore
├── README.md
│
├── credentials.json
├── token.json
│
├── src/
│   ├── __init__.py
│   ├── classifier.py
│   ├── config.py
│   ├── extractor.py
│   ├── gmail_service.py
│   ├── parser.py
│   └── model.pkl
│
└── templates/
    ├── login.html
    └── dashboard.html
```

> `credentials.json`, `token.json`, and `.env` contain sensitive credentials and must **not** be committed to GitHub.

---

# Requirements

Recommended environment:

* Python 3.11+
* Python 3.12 supported
* Google Cloud project
* Google OAuth 2.0 Web Client
* Gmail API enabled
* Gmail OAuth credentials
* Git

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Environment Configuration

Create a `.env` file in the project root.

```env
PROJECT_NAME=Statement Document Classifier
API_V1_STR=/api/v1

MODEL_PATH=src/model.pkl

GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json

AUTO_GMAIL_DETECTION_ENABLED=true
GMAIL_POLL_INTERVAL_SECONDS=60

GOOGLE_CLIENT_ID=YOUR_GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=YOUR_GOOGLE_CLIENT_SECRET

GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback

SESSION_SECRET_KEY=YOUR_LONG_RANDOM_SECRET
```

## Important

Never commit the real values of:

```text
GOOGLE_CLIENT_SECRET
SESSION_SECRET_KEY
credentials.json
token.json
```

Generate a strong session secret instead of using a placeholder.

For example:

```python
import secrets

print(secrets.token_urlsafe(32))
```

Copy the generated value into:

```env
SESSION_SECRET_KEY=generated-value
```

---

# Google OAuth Configuration

The application uses Google OAuth 2.0.

Your Google Cloud OAuth client should be a:

```text
Web application
```

The authorized redirect URI must exactly match:

```text
http://127.0.0.1:8000/auth/google/callback
```

The authorized JavaScript origin should be:

```text
http://127.0.0.1:8000
```

Do not accidentally configure:

```text
http://localhost:8000/auth/google/callback
```

while the application uses:

```text
http://127.0.0.1:8000/auth/google/callback
```

Although both point to the local machine, Google OAuth treats them as different URIs.

---

# Google OAuth Client ID vs Client Secret

The `.env` configuration must contain the credentials belonging to the **same OAuth client**.

For example:

```env
GOOGLE_CLIENT_ID=YOUR_CLIENT_ID
GOOGLE_CLIENT_SECRET=YOUR_CLIENT_SECRET
```

Do not mix:

```text
Client ID from OAuth Client A
+
Client Secret from OAuth Client B
```

This causes:

```text
invalid_client
The provided client secret is invalid.
```

If Google returns:

```text
HTTP/1.1 401 Unauthorized
```

during:

```text
POST https://oauth2.googleapis.com/token
```

and the error is:

```text
invalid_client
```

the first things to verify are:

1. Client ID is correct.
2. Client secret belongs to that exact client.
3. The secret has not been deleted.
4. `.env` contains the actual secret, not a placeholder.
5. The application is loading the intended `.env`.
6. There are no accidental quotes or extra characters.
7. The server was restarted after changing `.env`.

---

# Gmail Configuration

Gmail integration requires a Google OAuth credential file.

The configured path is:

```env
GMAIL_CREDENTIALS_FILE=credentials.json
```

The file should be available from the application's working directory, or `src/config.py` should resolve it to an absolute project path.

Expected file:

```text
statement-document-classifier/
└── credentials.json
```

After successful Gmail OAuth authentication, the application may create:

```text
token.json
```

Do not commit either file.

If the application reports:

```text
Gmail OAuth credentials file was not found: credentials.json
```

then the application cannot initialize Gmail authentication.

If it reports:

```text
Gmail API service is not authenticated.
Skipping Gmail polling.
```

the Gmail background worker is running, but Gmail authentication has not been established.

This is separate from the Google login flow.

---

# Google OAuth Login Flow

The authentication flow is:

```text
/
│
├── Login page
│
▼
/auth/login
│
├── Redirect to Google
│
▼
Google authentication
│
▼
/auth/google/callback
│
├── Authorization code exchanged for token
│
├── User information retrieved
│
├── User stored in session
│
▼
/dashboard
```

Logout:

```text
/auth/logout
```

---

# Running the Application

From the project root:

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Or:

```bash
python app.py
```

The application will be available at:

```text
http://127.0.0.1:8000
```

Login:

```text
http://127.0.0.1:8000/
```

Health check:

```text
http://127.0.0.1:8000/health
```

---

# API Endpoints

## Login

```http
GET /
```

Displays the login page.

---

## Start Google OAuth

```http
GET /auth/login
```

Redirects the browser to Google.

---

## Google OAuth Callback

```http
GET /auth/google/callback
```

Google redirects the user here after authentication.

---

## Dashboard

```http
GET /dashboard
```

Protected endpoint.

Requires an authenticated session.

---

## Logout

```http
GET /auth/logout
```

Clears the current session.

---

## Classify Statement

```http
POST /api/v1/classify-statement
```

Accepts a PDF upload and returns the classification and extracted fields.

Example:

```bash
curl -X POST \
  http://127.0.0.1:8000/api/v1/classify-statement \
  -F "file=@statement.pdf"
```

Authentication is required.

---

## Processed Statements

```http
GET /api/v1/processed-statements
```

Returns statements processed from Gmail.

Authentication is required.

---

## Gmail Webhook

```http
POST /api/v1/gmail-webhook
```

Receives Gmail Pub/Sub notifications.

For production, the webhook must validate the Pub/Sub request before processing it.

---

## Health Check

```http
GET /health
```

Example response:

```json
{
  "status": "healthy",
  "google_oauth_configured": true,
  "gmail_authenticated": true,
  "gmail_auto_detection": true,
  "processed_statements": 0
}
```

---

# PDF Processing Pipeline

Uploaded statements follow this pipeline:

```text
PDF
 │
 ▼
PDFExtractor
 │
 ▼
Extracted Text
 │
 ▼
StatementClassifier
 │
 ▼
Document Type
 │
 ▼
StatementParser
 │
 ▼
Structured Data
```

The trained model is loaded from:

```text
src/model.pkl
```

Configured through:

```env
MODEL_PATH=src/model.pkl
```

---

# Gmail Auto Detection

When enabled:

```env
AUTO_GMAIL_DETECTION_ENABLED=true
```

the application starts a background polling task.

The default polling interval is:

```env
GMAIL_POLL_INTERVAL_SECONDS=60
```

The worker performs:

```text
Start application
       │
       ▼
Gmail worker starts
       │
       ▼
Check Gmail
       │
       ▼
Find unread PDF statements
       │
       ▼
Download PDF
       │
       ▼
Classify statement
       │
       ▼
Extract fields
       │
       ▼
Store result
       │
       ▼
Mark Gmail message as read
       │
       ▼
Wait 60 seconds
       │
       └──────────────► Repeat
```

A message should only be marked as read after successful processing.

---

# Troubleshooting

## `invalid_client`

Error:

```text
OAuthError: invalid_client:
The provided client secret is invalid.
```

This means Google rejected the client credentials during the token exchange.

Check:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

Make sure both values belong to the same Google OAuth Web Client.

Restart the server after changing `.env`.

---

## `google_login_failed`

Example:

```text
/?error=google_login_failed&reason=invalid_client
```

This URL is not the root cause.

It is your application's error redirect.

The important error is in the server log:

```text
invalid_client:
The provided client secret is invalid.
```

Fix the Google OAuth client credentials first.

---

## `Access blocked: Authorization Error`

If Google displays:

```text
Access blocked: Authorization Error
```

check the Google Cloud OAuth configuration.

Verify:

* OAuth client type is `Web application`
* Redirect URI is correct
* OAuth consent screen is configured
* Test user is added when the application is in testing mode
* Required APIs are enabled
* The OAuth client belongs to the intended Google Cloud project

---

## Gmail authentication warning

If the application displays:

```text
Gmail API service is not authenticated.
Skipping Gmail polling.
```

this means Gmail processing is unavailable.

It does **not necessarily mean Google website login failed**.

Check:

```text
credentials.json
token.json
```

and the Gmail OAuth configuration.

---

## `credentials.json` not found

Error:

```text
Gmail OAuth credentials file was not found: credentials.json
```

Make sure:

```text
credentials.json
```

exists where the application expects it.

Check the configured value:

```env
GMAIL_CREDENTIALS_FILE=credentials.json
```

---

# Security

This project handles OAuth credentials and potentially sensitive financial statements.

Never commit:

```text
.env
credentials.json
token.json
```

A recommended `.gitignore` is:

```gitignore
# Environment
.env
.env.*
!.env.example

# Google credentials
credentials.json
token.json

# Python
__pycache__/
*.py[cod]
*.pyo

# Virtual environments
.venv/
venv/
env/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# Logs
*.log

# Test/cache
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

If a Google client secret has ever been committed to GitHub, treat it as compromised and rotate it in Google Cloud immediately.

---

# GitHub Setup

Initialize Git:

```bash
git init
```

Check files:

```bash
git status
```

Make sure `.env`, `credentials.json`, and `token.json` are ignored.

Add files:

```bash
git add .
```

Create the first commit:

```bash
git commit -m "Initial commit: statement document classifier"
```

Create a GitHub repository and connect it:

```bash
git remote add origin YOUR_GITHUB_REPOSITORY_URL
```

Rename the branch:

```bash
git branch -M main
```

Push:

```bash
git push -u origin main
```

---

# Environment Template for GitHub

Commit `.env.example`, but never commit `.env`.

Example:

```env
PROJECT_NAME=Statement Document Classifier
API_V1_STR=/api/v1
MODEL_PATH=src/model.pkl

GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json

AUTO_GMAIL_DETECTION_ENABLED=true
GMAIL_POLL_INTERVAL_SECONDS=60

GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback

SESSION_SECRET_KEY=generate-a-secure-random-value
```

---

# Production Considerations

The current application uses in-memory storage:

```python
PROCESSED_STATEMENTS_STORE
```

This is appropriate for local development but should not be used as the permanent production datastore.

A production architecture should use:

```text
PostgreSQL
    │
    ├── Users
    ├── Statements
    ├── Gmail messages
    └── Processing status

Redis
    │
    └── Background jobs / caching

FastAPI
    │
    ├── Authentication
    ├── API
    └── Statement processing

Worker
    │
    └── Gmail / PDF processing
```

Additional production requirements include:

* HTTPS
* Secure session cookies
* CSRF protection where applicable
* Persistent database storage
* Structured logging
* Secret management
* OAuth credential rotation
* Gmail Pub/Sub verification
* Request size limits
* PDF validation
* Rate limiting
* Error monitoring
* Background job management
* Database transactions
* Proper authorization rules

For production HTTPS, the session middleware should use:

```python
https_only=True
```

---

# Development Checklist

Before starting the application:

```text
[ ] Python environment created
[ ] Dependencies installed
[ ] .env created
[ ] GOOGLE_CLIENT_ID configured
[ ] GOOGLE_CLIENT_SECRET configured
[ ] GOOGLE_REDIRECT_URI configured
[ ] SESSION_SECRET_KEY configured
[ ] credentials.json available
[ ] Gmail API enabled
[ ] OAuth consent screen configured
[ ] OAuth test user configured if required
[ ] Authorized redirect URI configured
[ ] model.pkl available
[ ] templates available
```

Then start:

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Check:

```text
http://127.0.0.1:8000/health
```

Then test:

```text
http://127.0.0.1:8000/
```

---

# Important Credential Rule

Never use a placeholder in a running application:

```env
GOOGLE_CLIENT_SECRET=PUT_THE_CURRENT_SECRET_HERE
```

Replace it with the actual secret belonging to the same OAuth client ID.

Likewise:

```env
SESSION_SECRET_KEY=PUT_A_LONG_RANDOM_SECRET_HERE
```

must be replaced with a real randomly generated secret.

Do not paste either secret into GitHub, README files, screenshots, issue trackers, or public chats.

---

# License

Add the project's intended license here, for example:

```text
MIT License
```

if the project is intended to be released under MIT.

---

# Status

Current project capabilities:

* Google OAuth authentication
* Protected dashboard
* PDF statement classification
* Statement parsing
* Gmail statement detection
* Gmail background processing
* Gmail webhook endpoint
* Health monitoring
* Local development support

For production deployment, persistent storage, secure secret management, HTTPS, webhook verification, and stronger authorization should be implemented before exposing the application publicly.

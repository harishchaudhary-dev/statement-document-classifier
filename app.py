"""
Statement Document Classifier
FastAPI application with Google OAuth login and Gmail processing.

Application flow:

    /                       -> Login page
    /auth/login             -> Start Google OAuth
    /auth/google/callback   -> Google OAuth callback
    /dashboard              -> Protected dashboard
    /auth/logout            -> Logout
    /health                 -> Health check

FastAPI documentation is intentionally disabled.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import uvicorn
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from src.classifier import StatementClassifier
from src.config import settings
from src.extractor import PDFExtractor
from src.gmail_service import GmailService
from src.parser import StatementParser


# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("StatementClassifier")


# ============================================================================
# Paths
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


# ============================================================================
# Application dependencies
# ============================================================================

classifier = StatementClassifier()
gmail_service = GmailService()

templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
)


# ============================================================================
# In-memory statement storage
# ============================================================================
#
# Suitable for local development.
# Production should use PostgreSQL/Redis/etc.
# ============================================================================

PROCESSED_STATEMENTS_STORE: List[Dict[str, Any]] = []

MAX_PROCESSED_STATEMENTS = 1000

PROCESSED_MESSAGE_IDS: set[str] = set()


# ============================================================================
# Google OAuth
# ============================================================================

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID.strip(),
    client_secret=settings.GOOGLE_CLIENT_SECRET.strip(),
    server_metadata_url=(
        "https://accounts.google.com/"
        ".well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": "openid profile email",
    },
)


# ============================================================================
# OAuth configuration validation
# ============================================================================

def validate_oauth_configuration() -> None:
    """
    Validate Google OAuth configuration.

    Never logs the Google client secret.
    """

    client_id = settings.GOOGLE_CLIENT_ID.strip()
    client_secret = settings.GOOGLE_CLIENT_SECRET.strip()
    redirect_uri = settings.GOOGLE_REDIRECT_URI.strip()

    if not client_id:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID is missing from environment configuration."
        )

    if not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_SECRET is missing from environment configuration."
        )

    if not redirect_uri:
        raise RuntimeError(
            "GOOGLE_REDIRECT_URI is missing from environment configuration."
        )

    expected_redirect_uri = (
        "http://127.0.0.1:8000/auth/google/callback"
    )

    if redirect_uri != expected_redirect_uri:
        logger.warning(
            "Configured GOOGLE_REDIRECT_URI is %s. "
            "Expected local URI is %s.",
            redirect_uri,
            expected_redirect_uri,
        )

    logger.info("Google OAuth configuration loaded.")
    logger.info(
        "Google OAuth client ID: %s",
        client_id,
    )
    logger.info(
        "Google OAuth redirect URI: %s",
        redirect_uri,
    )

    # Intentionally NEVER log GOOGLE_CLIENT_SECRET.


# ============================================================================
# Authentication helpers
# ============================================================================

def get_current_user(
    request: Request,
) -> Optional[Dict[str, Any]]:
    """
    Return the authenticated Google user.

    Returns:
        User dictionary when authenticated.
        None otherwise.
    """

    user = request.session.get("user")

    if not isinstance(user, dict):
        return None

    return user


def require_authentication(
    request: Request,
) -> Dict[str, Any]:
    """
    Require an authenticated user.
    """

    user = get_current_user(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )

    return user


# ============================================================================
# Error redirect helper
# ============================================================================

def oauth_error_redirect(
    *,
    reason: str,
    status_code: int = 303,
) -> RedirectResponse:
    """
    Redirect to login page with a safe OAuth error reason.

    The actual exception is logged server-side.
    Sensitive details are never sent to the browser.
    """

    query = urlencode(
        {
            "error": "google_login_failed",
            "reason": reason,
        }
    )

    return RedirectResponse(
        url=f"/?{query}",
        status_code=status_code,
    )


# ============================================================================
# Statement storage
# ============================================================================

def add_processed_statement(
    record: Dict[str, Any],
) -> bool:
    """
    Add a processed statement.

    Returns:
        True if inserted.
        False if duplicate Gmail message.
    """

    message_id = record.get("message_id")

    if message_id:
        if message_id in PROCESSED_MESSAGE_IDS:
            logger.info(
                "Skipping duplicate Gmail message: %s",
                message_id,
            )
            return False

        PROCESSED_MESSAGE_IDS.add(message_id)

    PROCESSED_STATEMENTS_STORE.insert(
        0,
        record,
    )

    if len(PROCESSED_STATEMENTS_STORE) > MAX_PROCESSED_STATEMENTS:
        del PROCESSED_STATEMENTS_STORE[
            MAX_PROCESSED_STATEMENTS:
        ]

    return True


# ============================================================================
# PDF statement processing
# ============================================================================

def process_statement(
    *,
    pdf_bytes: bytes,
    filename: str,
    message_id: Optional[str] = None,
    sender: Optional[str] = None,
    subject: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract, classify and parse a PDF statement.
    """

    if not pdf_bytes:
        raise ValueError(
            "PDF file is empty."
        )

    logger.info(
        "Processing statement: %s",
        filename,
    )

    # ------------------------------------------------------------------------
    # Extract PDF text
    # ------------------------------------------------------------------------

    text = PDFExtractor.extract_text_from_bytes(
        pdf_bytes
    )

    if not text or not text.strip():
        raise ValueError(
            f"Unable to extract text from PDF: {filename}"
        )

    # ------------------------------------------------------------------------
    # Classify document
    # ------------------------------------------------------------------------

    doc_type = classifier.predict(
        text
    )

    # ------------------------------------------------------------------------
    # Parse fields
    # ------------------------------------------------------------------------

    extracted_fields = StatementParser.parse_fields(
        text,
        doc_type,
    )

    return {
        "message_id": message_id,
        "sender": sender,
        "subject": subject,
        "filename": filename,
        "doc_type": doc_type,
        "extracted_data": extracted_fields,
        "raw_text_snippet": text[:300],
    }


# ============================================================================
# Gmail processing
# ============================================================================

def process_gmail_statements() -> int:
    """
    Fetch and process unread Gmail PDF statements.

    Gmail messages are marked as read only after successful processing.
    """

    processed_count = 0

    # ------------------------------------------------------------------------
    # Check Gmail authentication
    # ------------------------------------------------------------------------

    try:
        if hasattr(
            gmail_service,
            "is_authenticated",
        ):
            authenticated = gmail_service.is_authenticated()
        else:
            authenticated = (
                getattr(
                    gmail_service,
                    "service",
                    None,
                )
                is not None
            )

    except Exception:
        logger.exception(
            "Unable to determine Gmail authentication state."
        )
        return 0

    if not authenticated:
        logger.warning(
            "Gmail API service is not authenticated. "
            "Skipping Gmail polling."
        )
        return 0

    # ------------------------------------------------------------------------
    # Fetch Gmail statements
    # ------------------------------------------------------------------------

    try:
        logger.info(
            "Checking Gmail for unread statement PDFs..."
        )

        attachments = (
            gmail_service.fetch_unread_statement_pdfs()
        )

        logger.info(
            "Gmail returned %d PDF attachment(s).",
            len(attachments),
        )

        for item in attachments:

            filename = item.get(
                "filename",
                "unknown.pdf",
            )

            message_id = item.get(
                "message_id"
            )

            try:
                record = process_statement(
                    pdf_bytes=item["pdf_bytes"],
                    filename=filename,
                    message_id=message_id,
                    sender=item.get("sender"),
                    subject=item.get("subject"),
                )

                inserted = add_processed_statement(
                    record
                )

                if not inserted:
                    continue

                # ------------------------------------------------------------
                # Mark email as read only after successful processing.
                # ------------------------------------------------------------

                if (
                    message_id
                    and hasattr(
                        gmail_service,
                        "mark_message_as_read",
                    )
                ):
                    gmail_service.mark_message_as_read(
                        message_id
                    )

                processed_count += 1

                logger.info(
                    "Processed Gmail statement: %s -> %s",
                    filename,
                    record["doc_type"],
                )

            except Exception:
                logger.exception(
                    "Failed to process Gmail attachment: %s",
                    filename,
                )

    except Exception:
        logger.exception(
            "Failed to fetch Gmail statements."
        )

    return processed_count


# ============================================================================
# Gmail background worker
# ============================================================================

async def gmail_auto_detector_loop(
    stop_event: asyncio.Event,
) -> None:
    """
    Background Gmail polling worker.

    Blocking Gmail/PDF/ML operations are executed in a worker thread.
    """

    logger.info(
        "Starting Gmail auto-detector task..."
    )

    poll_interval = max(
        5,
        int(
            settings.GMAIL_POLL_INTERVAL_SECONDS
        ),
    )

    while not stop_event.is_set():

        try:

            if settings.AUTO_GMAIL_DETECTION_ENABLED:

                processed_count = (
                    await asyncio.to_thread(
                        process_gmail_statements
                    )
                )

                if processed_count:
                    logger.info(
                        "Gmail auto-detector processed "
                        "%d statement(s).",
                        processed_count,
                    )

        except asyncio.CancelledError:

            logger.info(
                "Gmail auto-detector cancellation requested."
            )

            raise

        except Exception:

            logger.exception(
                "Unexpected Gmail worker error."
            )

        try:

            await asyncio.wait_for(
                stop_event.wait(),
                timeout=poll_interval,
            )

        except asyncio.TimeoutError:
            pass

    logger.info(
        "Gmail auto-detector stopped."
    )


# ============================================================================
# Application lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    """
    Manage application startup and shutdown.
    """

    # ------------------------------------------------------------------------
    # Validate OAuth configuration at startup.
    # ------------------------------------------------------------------------

    validate_oauth_configuration()

    stop_event = asyncio.Event()

    gmail_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------------
    # Start Gmail worker if enabled.
    # ------------------------------------------------------------------------

    if settings.AUTO_GMAIL_DETECTION_ENABLED:

        gmail_task = asyncio.create_task(
            gmail_auto_detector_loop(
                stop_event
            ),
            name="gmail-auto-detector",
        )

    logger.info(
        "Application startup completed."
    )

    try:

        yield

    finally:

        logger.info(
            "Application shutdown started."
        )

        stop_event.set()

        if gmail_task:

            try:

                await asyncio.wait_for(
                    gmail_task,
                    timeout=10,
                )

            except asyncio.TimeoutError:

                logger.warning(
                    "Gmail worker did not stop within "
                    "10 seconds. Cancelling."
                )

                gmail_task.cancel()

                try:
                    await gmail_task

                except asyncio.CancelledError:
                    pass

            except asyncio.CancelledError:

                logger.info(
                    "Gmail worker cancelled."
                )

        logger.info(
            "Application shutdown completed."
        )


# ============================================================================
# FastAPI application
# ============================================================================

app = FastAPI(
    title=settings.PROJECT_NAME,

    # Disable Swagger UI.
    docs_url=None,

    # Disable ReDoc.
    redoc_url=None,

    # Disable OpenAPI JSON.
    openapi_url=None,

    lifespan=lifespan,
)


# ============================================================================
# Session middleware
# ============================================================================

app.add_middleware(
    SessionMiddleware,

    secret_key=settings.SESSION_SECRET_KEY,

    session_cookie=(
        "statement_classifier_session"
    ),

    max_age=60 * 60 * 24 * 7,

    same_site="lax",

    # False for local HTTP development.
    # Set True when deployed behind HTTPS.
    https_only=False,
)


# ============================================================================
# Login page
# ============================================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
async def login_page(
    request: Request,
):
    """
    Display the login page.
    """

    user = get_current_user(
        request
    )

    if user:

        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,

            "error": request.query_params.get(
                "error"
            ),

            "reason": request.query_params.get(
                "reason"
            ),
        },
    )


# ============================================================================
# Google OAuth login
# ============================================================================

@app.get(
    "/auth/login",
)
async def google_login(
    request: Request,
):
    """
    Start Google OAuth authentication.
    """

    logger.info(
        "Starting Google OAuth login."
    )

    logger.info(
        "OAuth client ID: %s",
        settings.GOOGLE_CLIENT_ID,
    )

    logger.info(
        "OAuth redirect URI: %s",
        settings.GOOGLE_REDIRECT_URI,
    )

    # This must exactly match the URI configured
    # in Google Cloud Console.
    redirect_uri = (
        settings.GOOGLE_REDIRECT_URI
    )

    return await oauth.google.authorize_redirect(
        request,
        redirect_uri,
        prompt="select_account",
    )


# ============================================================================
# Google OAuth callback
# ============================================================================

@app.get(
    "/auth/google/callback",
    name="google_callback",
)
async def google_callback(
    request: Request,
):
    """
    Handle Google's OAuth callback.
    """

    logger.info(
        "Received Google OAuth callback."
    )

    # ------------------------------------------------------------------------
    # Google can return an OAuth error before sending a code.
    # ------------------------------------------------------------------------

    google_error = request.query_params.get(
        "error"
    )

    if google_error:

        error_description = (
            request.query_params.get(
                "error_description"
            )
        )

        logger.error(
            "Google returned OAuth error: %s | description=%s",
            google_error,
            error_description,
        )

        request.session.clear()

        return oauth_error_redirect(
            reason="GoogleOAuthError"
        )

    # ------------------------------------------------------------------------
    # Exchange authorization code for token.
    # ------------------------------------------------------------------------

    try:

        token = await oauth.google.authorize_access_token(
            request
        )

        if not token:

            raise ValueError(
                "Google returned an empty OAuth token."
            )

        logger.info(
            "Google OAuth token exchange completed."
        )

    except OAuthError as exc:

        # ------------------------------------------------------------
        # This is where your previous error occurred:
        #
        # invalid_client:
        # The provided client secret is invalid.
        #
        # ------------------------------------------------------------

        logger.exception(
            "Google OAuth token exchange failed."
        )

        request.session.clear()

        oauth_error_code = getattr(
            exc,
            "error",
            None,
        )

        if oauth_error_code:
            reason = str(
                oauth_error_code
            )
        else:
            reason = "OAuthError"

        return oauth_error_redirect(
            reason=reason
        )

    except Exception:

        logger.exception(
            "Unexpected OAuth token exchange failure."
        )

        request.session.clear()

        return oauth_error_redirect(
            reason="TokenExchangeError"
        )

    # ------------------------------------------------------------------------
    # Get Google user information.
    # ------------------------------------------------------------------------

    try:

        # With OpenID Connect configured correctly,
        # Authlib normally places parsed user information
        # in token["userinfo"].
        user_info = token.get(
            "userinfo"
        )

        if not user_info:

            user_info = (
                await oauth.google.parse_id_token(
                    request,
                    token,
                )
            )

        if not user_info:

            raise ValueError(
                "Google did not return user information."
            )

    except Exception:

        logger.exception(
            "Unable to parse Google user information."
        )

        request.session.clear()

        return oauth_error_redirect(
            reason="UserInfoError"
        )

    # ------------------------------------------------------------------------
    # Validate email.
    # ------------------------------------------------------------------------

    email = user_info.get(
        "email"
    )

    if not email:

        logger.error(
            "Google account email was not returned."
        )

        request.session.clear()

        return oauth_error_redirect(
            reason="EmailMissing"
        )

    # ------------------------------------------------------------------------
    # Create application session.
    # ------------------------------------------------------------------------

    request.session["user"] = {
        "id": user_info.get(
            "sub"
        ),

        "email": email,

        "name": user_info.get(
            "name",
            email,
        ),

        "picture": user_info.get(
            "picture"
        ),
    }

    # Store ID token if you later want
    # OpenID Connect logout.
    if token.get("id_token"):
        request.session["id_token"] = token[
            "id_token"
        ]

    logger.info(
        "Google login successful: %s",
        email,
    )

    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


# ============================================================================
# Logout
# ============================================================================

@app.get(
    "/auth/logout",
)
async def logout(
    request: Request,
):
    """
    Destroy the authenticated application session.
    """

    user = get_current_user(
        request
    )

    if user:

        logger.info(
            "User logged out: %s",
            user.get("email"),
        )

    request.session.clear()

    return RedirectResponse(
        url="/",
        status_code=303,
    )


# ============================================================================
# Protected dashboard
# ============================================================================

@app.get(
    "/dashboard",
    response_class=HTMLResponse,
)
async def dashboard(
    request: Request,
):
    """
    Display protected dashboard.
    """

    user = get_current_user(
        request
    )

    if not user:

        return RedirectResponse(
            url="/",
            status_code=303,
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,

            "user": user,

            "processed_count": len(
                PROCESSED_STATEMENTS_STORE
            ),

            "statements": (
                PROCESSED_STATEMENTS_STORE
            ),
        },
    )


# ============================================================================
# PDF classification endpoint
# ============================================================================

@app.post(
    f"{settings.API_V1_STR}/classify-statement",
)
async def classify_uploaded_statement(
    request: Request,
    file: UploadFile = File(...),
):
    """
    Classify an uploaded PDF.

    Authentication is required.
    """

    require_authentication(
        request
    )

    filename = (
        file.filename
        or "uploaded_file.pdf"
    )

    if not filename.lower().endswith(
        ".pdf"
    ):

        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported.",
        )

    try:

        content = await file.read()

        if not content:

            raise HTTPException(
                status_code=400,
                detail="Uploaded PDF is empty.",
            )

        record = await asyncio.to_thread(
            process_statement,
            pdf_bytes=content,
            filename=filename,
        )

        return {
            "filename": filename,
            "status": "success",
            "doc_type": record[
                "doc_type"
            ],
            "extracted_data": record[
                "extracted_data"
            ],
            "raw_text_snippet": record[
                "raw_text_snippet"
            ],
        }

    except HTTPException:
        raise

    except ValueError as exc:

        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception:

        logger.exception(
            "Failed to process uploaded PDF."
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to process statement.",
        )

    finally:

        await file.close()


# ============================================================================
# Processed Gmail statements
# ============================================================================

@app.get(
    f"{settings.API_V1_STR}/processed-statements",
)
async def processed_statements(
    request: Request,
):
    """
    Return processed Gmail statements.

    Authentication is required.
    """

    require_authentication(
        request
    )

    return {
        "count": len(
            PROCESSED_STATEMENTS_STORE
        ),
        "statements": (
            PROCESSED_STATEMENTS_STORE
        ),
    }


# ============================================================================
# Gmail webhook
# ============================================================================

@app.post(
    f"{settings.API_V1_STR}/gmail-webhook",
)
async def gmail_webhook(
    request: Request,
):
    """
    Gmail Pub/Sub webhook.

    Production deployments should verify
    the Pub/Sub push request.
    """

    try:

        data = await request.json()

    except Exception as exc:

        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload.",
        ) from exc

    logger.info(
        "Received Gmail Pub/Sub notification."
    )

    logger.debug(
        "Pub/Sub payload: %s",
        data,
    )

    await asyncio.to_thread(
        process_gmail_statements
    )

    return {
        "status": "accepted",
    }


# ============================================================================
# Health check
# ============================================================================

@app.get(
    "/health",
)
async def health_check():
    """
    Application health check.
    """

    gmail_authenticated = False

    try:

        if hasattr(
            gmail_service,
            "is_authenticated",
        ):

            gmail_authenticated = (
                gmail_service.is_authenticated()
            )

        else:

            gmail_authenticated = (
                getattr(
                    gmail_service,
                    "service",
                    None,
                )
                is not None
            )

    except Exception:

        logger.exception(
            "Unable to determine Gmail authentication status."
        )

    return {
        "status": "healthy",

        "google_oauth_configured": bool(
            settings.GOOGLE_CLIENT_ID
            and settings.GOOGLE_CLIENT_SECRET
        ),

        "google_client_id": (
            settings.GOOGLE_CLIENT_ID
        ),

        "google_redirect_uri": (
            settings.GOOGLE_REDIRECT_URI
        ),

        "gmail_authenticated": (
            gmail_authenticated
        ),

        "gmail_auto_detection": bool(
            settings.AUTO_GMAIL_DETECTION_ENABLED
        ),

        "processed_statements": len(
            PROCESSED_STATEMENTS_STORE
        ),
    }


# ============================================================================
# Local development
# ============================================================================

if __name__ == "__main__":

    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
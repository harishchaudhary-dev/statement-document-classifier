# src/gmail_service.py

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from src.config import settings


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("GmailService")


# ---------------------------------------------------------------------------
# Gmail API configuration
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

GMAIL_USER = "me"


# ---------------------------------------------------------------------------
# Gmail Service
# ---------------------------------------------------------------------------

class GmailService:
    """
    Production-oriented Gmail API service.

    Responsibilities:
        - Authenticate with Gmail using OAuth 2.0.
        - Refresh existing credentials.
        - Fetch unread emails containing PDF attachments.
        - Recursively inspect Gmail MIME parts.
        - Download PDF attachments safely.
        - Mark successfully handled messages as read.
    """

    def __init__(self) -> None:
        self.creds: Optional[Credentials] = self._authenticate()

        self.service: Optional[Resource] = None

        if self.creds:
            try:
                self.service = build(
                    "gmail",
                    "v1",
                    credentials=self.creds,
                    cache_discovery=False,
                )

                logger.info("Gmail API service initialized successfully.")

            except Exception:
                logger.exception(
                    "Failed to initialize Gmail API service."
                )
                self.service = None

        else:
            logger.warning(
                "Gmail authentication unavailable. "
                "Gmail auto-detection will remain disabled."
            )

    # -----------------------------------------------------------------------
    # Authentication
    # -----------------------------------------------------------------------

    def _authenticate(self) -> Optional[Credentials]:
        """
        Authenticate against Gmail using OAuth 2.0.

        Authentication order:

            1. Load existing token.
            2. Refresh expired token when possible.
            3. Start OAuth browser flow if no valid token exists.
            4. Persist the new token for future runs.
        """

        credentials_file = Path(
            settings.GMAIL_CREDENTIALS_FILE
        ).expanduser()

        token_file = Path(
            settings.GMAIL_TOKEN_FILE
        ).expanduser()

        logger.info(
            "Gmail credentials file: %s",
            credentials_file,
        )

        logger.info(
            "Gmail token file: %s",
            token_file,
        )

        creds: Optional[Credentials] = None

        # -------------------------------------------------------------------
        # Validate OAuth client credentials
        # -------------------------------------------------------------------

        if not credentials_file.exists():
            logger.error(
                "Gmail OAuth credentials file was not found: %s",
                credentials_file,
            )

            return None

        # -------------------------------------------------------------------
        # Load existing token
        # -------------------------------------------------------------------

        if token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(token_file),
                    SCOPES,
                )

                logger.info(
                    "Existing Gmail OAuth token loaded successfully."
                )

            except Exception:
                logger.exception(
                    "Failed to load Gmail OAuth token: %s",
                    token_file,
                )

                creds = None

        # -------------------------------------------------------------------
        # Refresh expired token
        # -------------------------------------------------------------------

        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info(
                    "Gmail OAuth token expired. Refreshing token..."
                )

                creds.refresh(Request())

                self._save_credentials(
                    creds=creds,
                    token_file=token_file,
                )

                logger.info(
                    "Gmail OAuth token refreshed successfully."
                )

            except Exception:
                logger.exception(
                    "Failed to refresh Gmail OAuth token."
                )

                creds = None

        # -------------------------------------------------------------------
        # Existing valid credentials
        # -------------------------------------------------------------------

        if creds and creds.valid:
            logger.info(
                "Gmail OAuth authentication is valid."
            )

            return creds

        # -------------------------------------------------------------------
        # Start OAuth browser flow
        # -------------------------------------------------------------------

        try:
            logger.info(
                "Starting Gmail OAuth 2.0 browser authentication..."
            )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_file),
                SCOPES,
            )

            creds = flow.run_local_server(
                port=0,
                access_type="offline",
                prompt="consent",
            )

            self._save_credentials(
                creds=creds,
                token_file=token_file,
            )

            logger.info(
                "Gmail OAuth authentication completed successfully."
            )

            return creds

        except Exception:
            logger.exception(
                "Gmail OAuth authentication failed."
            )

            return None

    # -----------------------------------------------------------------------
    # Save credentials
    # -----------------------------------------------------------------------

    @staticmethod
    def _save_credentials(
        *,
        creds: Credentials,
        token_file: Path,
    ) -> None:
        """
        Persist OAuth credentials to disk.
        """

        try:
            token_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            token_file.write_text(
                creds.to_json(),
                encoding="utf-8",
            )

            logger.info(
                "Gmail OAuth token saved to: %s",
                token_file,
            )

        except Exception:
            logger.exception(
                "Failed to save Gmail OAuth token."
            )

    # -----------------------------------------------------------------------
    # Gmail message listing
    # -----------------------------------------------------------------------

    def _list_messages(
        self,
        *,
        query: str,
        max_results: int = 100,
    ) -> List[Dict[str, str]]:
        """
        Retrieve Gmail message IDs matching a search query.

        Handles Gmail pagination.
        """

        if not self.service:
            logger.warning(
                "Gmail service is unavailable."
            )
            return []

        messages: List[Dict[str, str]] = []

        page_token: Optional[str] = None

        try:
            while len(messages) < max_results:

                remaining = max_results - len(messages)

                response = (
                    self.service.users()
                    .messages()
                    .list(
                        userId=GMAIL_USER,
                        q=query,
                        maxResults=min(100, remaining),
                        pageToken=page_token,
                    )
                    .execute()
                )

                page_messages = response.get(
                    "messages",
                    [],
                )

                messages.extend(page_messages)

                page_token = response.get(
                    "nextPageToken"
                )

                if not page_token or not page_messages:
                    break

        except Exception:
            logger.exception(
                "Failed to list Gmail messages."
            )

        return messages[:max_results]

    # -----------------------------------------------------------------------
    # Message headers
    # -----------------------------------------------------------------------

    @staticmethod
    def _get_header(
        headers: List[Dict[str, Any]],
        name: str,
        default: str = "",
    ) -> str:
        """
        Safely retrieve a Gmail message header.
        """

        target = name.lower()

        for header in headers:
            if (
                header.get("name", "").lower()
                == target
            ):
                return header.get(
                    "value",
                    default,
                )

        return default

    # -----------------------------------------------------------------------
    # MIME tree traversal
    # -----------------------------------------------------------------------

    def _find_pdf_parts(
        self,
        payload: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Recursively find all PDF attachment MIME parts.

        Gmail can represent attachments as nested MIME structures such as:

            multipart/mixed
                multipart/alternative
                    text/plain
                    text/html
                application/pdf

        Therefore, looking only at payload["parts"] is unreliable.
        """

        pdf_parts: List[Dict[str, Any]] = []

        def walk(part: Dict[str, Any]) -> None:
            filename = (
                part.get("filename")
                or ""
            ).strip()

            mime_type = (
                part.get("mimeType")
                or ""
            ).lower()

            body = part.get("body") or {}

            attachment_id = body.get(
                "attachmentId"
            )

            is_pdf = (
                mime_type == "application/pdf"
                or filename.lower().endswith(".pdf")
            )

            if (
                is_pdf
                and filename
                and attachment_id
            ):
                pdf_parts.append(part)

            for child in part.get(
                "parts",
                [],
            ):
                if isinstance(child, dict):
                    walk(child)

        walk(payload)

        return pdf_parts

    # -----------------------------------------------------------------------
    # Attachment download
    # -----------------------------------------------------------------------

    def _download_attachment(
        self,
        *,
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        """
        Download and decode a Gmail attachment.
        """

        if not self.service:
            raise RuntimeError(
                "Gmail API service is unavailable."
            )

        response = (
            self.service.users()
            .messages()
            .attachments()
            .get(
                userId=GMAIL_USER,
                messageId=message_id,
                id=attachment_id,
            )
            .execute()
        )

        encoded_data = response.get(
            "data"
        )

        if not encoded_data:
            raise ValueError(
                "Gmail attachment returned no data."
            )

        try:
            return base64.urlsafe_b64decode(
                encoded_data
                + "="
                * (
                    -len(encoded_data) % 4
                )
            )

        except Exception as exc:
            raise ValueError(
                "Failed to decode Gmail attachment."
            ) from exc

    # -----------------------------------------------------------------------
    # Fetch unread PDF statements
    # -----------------------------------------------------------------------

    def fetch_unread_statement_pdfs(
        self,
        *,
        max_messages: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Fetch unread Gmail messages containing PDF attachments.

        Returns:

            [
                {
                    "message_id": "...",
                    "sender": "...",
                    "subject": "...",
                    "filename": "...",
                    "pdf_bytes": b"...",
                }
            ]

        Important:
            Messages are NOT marked as read here.

        The caller should mark a message as read only after
        successful processing.
        """

        if not self.service:
            logger.warning(
                "Gmail API service is not authenticated. "
                "Skipping Gmail polling."
            )

            return []

        query = (
            "is:unread "
            "has:attachment "
            "filename:pdf"
        )

        logger.info(
            "Searching Gmail with query: %s",
            query,
        )

        messages = self._list_messages(
            query=query,
            max_results=max_messages,
        )

        if not messages:
            logger.info(
                "No unread Gmail messages with PDF attachments found."
            )

            return []

        logger.info(
            "Found %d unread Gmail message(s) with PDF attachments.",
            len(messages),
        )

        attachments_found: List[Dict[str, Any]] = []

        for message in messages:

            message_id = message.get("id")

            if not message_id:
                continue

            try:
                gmail_message = (
                    self.service.users()
                    .messages()
                    .get(
                        userId=GMAIL_USER,
                        id=message_id,
                        format="full",
                    )
                    .execute()
                )

                payload = (
                    gmail_message.get(
                        "payload"
                    )
                    or {}
                )

                headers = payload.get(
                    "headers",
                    [],
                )

                subject = self._get_header(
                    headers,
                    "Subject",
                    "No Subject",
                )

                sender = self._get_header(
                    headers,
                    "From",
                    "Unknown Sender",
                )

                pdf_parts = self._find_pdf_parts(
                    payload
                )

                if not pdf_parts:
                    logger.debug(
                        "Message %s contains no downloadable PDF attachments.",
                        message_id,
                    )
                    continue

                logger.info(
                    "Message %s contains %d PDF attachment(s).",
                    message_id,
                    len(pdf_parts),
                )

                for part in pdf_parts:

                    filename = (
                        part.get("filename")
                        or "statement.pdf"
                    )

                    body = (
                        part.get("body")
                        or {}
                    )

                    attachment_id = body.get(
                        "attachmentId"
                    )

                    if not attachment_id:
                        logger.warning(
                            "PDF attachment '%s' in message %s "
                            "has no attachment ID.",
                            filename,
                            message_id,
                        )
                        continue

                    try:
                        pdf_bytes = self._download_attachment(
                            message_id=message_id,
                            attachment_id=attachment_id,
                        )

                        if not pdf_bytes:
                            logger.warning(
                                "Downloaded PDF '%s' is empty.",
                                filename,
                            )
                            continue

                        record = {
                            "message_id": message_id,
                            "sender": sender,
                            "subject": subject,
                            "filename": filename,
                            "pdf_bytes": pdf_bytes,
                        }

                        attachments_found.append(
                            record
                        )

                        logger.info(
                            "Downloaded Gmail PDF: %s | message=%s | size=%d bytes",
                            filename,
                            message_id,
                            len(pdf_bytes),
                        )

                    except Exception:
                        logger.exception(
                            "Failed to download Gmail PDF '%s' "
                            "from message %s.",
                            filename,
                            message_id,
                        )

            except Exception:
                logger.exception(
                    "Failed to process Gmail message metadata: %s",
                    message_id,
                )

        logger.info(
            "Gmail polling completed. Downloaded %d PDF attachment(s).",
            len(attachments_found),
        )

        return attachments_found

    # -----------------------------------------------------------------------
    # Mark Gmail message as read
    # -----------------------------------------------------------------------

    def mark_message_as_read(
        self,
        message_id: str,
    ) -> bool:
        """
        Mark a Gmail message as read.

        This should be called AFTER the statement has been successfully
        classified and parsed.
        """

        if not self.service:
            logger.warning(
                "Cannot mark message as read: Gmail service unavailable."
            )
            return False

        if not message_id:
            logger.warning(
                "Cannot mark Gmail message as read: missing message ID."
            )
            return False

        try:
            (
                self.service.users()
                .messages()
                .modify(
                    userId=GMAIL_USER,
                    id=message_id,
                    body={
                        "removeLabelIds": [
                            "UNREAD"
                        ]
                    },
                )
                .execute()
            )

            logger.info(
                "Gmail message marked as read: %s",
                message_id,
            )

            return True

        except Exception:
            logger.exception(
                "Failed to mark Gmail message as read: %s",
                message_id,
            )

            return False

    # -----------------------------------------------------------------------
    # Health check
    # -----------------------------------------------------------------------

    def is_authenticated(self) -> bool:
        """
        Return whether Gmail API is ready.
        """

        return (
            self.service is not None
            and self.creds is not None
            and self.creds.valid
        )
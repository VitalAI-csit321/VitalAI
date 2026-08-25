"""Microsoft Graph mail client for the inbound connector.

Ported from Matthew's Inbox_Handling/Outlook_Reader.py and Email_Parser.py.
Endpoints, OData query parameters and JSON field paths are his; the transport
is rewritten on httpx because this codebase is async throughout and a blocking
requests call inside a FastAPI worker stalls the event loop.

Everything here is pure I/O plus one pure parse function. No database access,
no classification: outlook_sync_service owns that orchestration.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.schemas.email import EmailIngestRequest

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.microsoft.com/v1.0"
EXTERNAL_SOURCE = "outlook"

_TIMEOUT = httpx.Timeout(30.0)

# Strip <script>/<style> blocks including their contents before the general tag
# strip. The original regex only removed the tags themselves, which left raw CSS
# in the message body -- real Outlook HTML mail routinely carries a large <style>
# block, and that text would otherwise be fed to the classifier as if the patient
# had written it.
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    # Entities survive tag stripping, so "&amp;" would reach the classifier
    # verbatim without this.
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _parse_received(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Graph returns RFC 3339 with a trailing Z, which fromisoformat only
        # accepts as +00:00 before Python 3.11.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Unparseable receivedDateTime from Graph: %r", value)
        return None


def to_ingest_request(message: dict[str, Any]) -> EmailIngestRequest | None:
    """Map one Graph message onto the pipeline's existing ingest contract.

    Returns None for a message that cannot be represented (no id, or an empty
    body once HTML is stripped) rather than raising, so one malformed message
    never aborts a whole poll cycle.
    """
    message_id = message.get("id")
    if not message_id:
        logger.warning("Graph message with no id, skipping")
        return None

    sender = (message.get("from") or {}).get("emailAddress", {}).get("address", "")
    if not sender:
        logger.warning("Graph message %s has no sender address, skipping", message_id)
        return None

    recipients = message.get("toRecipients") or []
    recipient = ""
    if recipients:
        recipient = recipients[0].get("emailAddress", {}).get("address", "")
    if not recipient:
        # Mail delivered to a shared mailbox can arrive with toRecipients absent.
        # The connector's own mailbox is the honest stand-in, and the schema
        # requires a valid address.
        recipient = settings.outlook_mailbox_address or sender

    body = strip_html((message.get("body") or {}).get("content", ""))
    if not body:
        logger.info("Graph message %s has an empty body after stripping, skipping", message_id)
        return None

    # EmailIngestRequest enforces min_length=1 on subject; a genuinely blank
    # subject line is legal in mail and would otherwise fail validation.
    subject = (message.get("subject") or "").strip() or "(no subject)"

    return EmailIngestRequest(
        sender=sender,
        recipient=recipient,
        subject=subject[:500],
        body=body,
        external_id=message_id,
        external_source=EXTERNAL_SOURCE,
        received_at=_parse_received(message.get("receivedDateTime")),
    )


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def get_unread_emails(access_token: str, top: int | None = None) -> list[dict[str, Any]]:
    """Fetch unread inbox messages, newest first.

    Query parameters are Matthew's, with two additions: $top (his version had
    no page cap, which is unsafe for something that runs on a timer) and
    toRecipients in $select, which the pipeline needs for Email.recipient.
    """
    params = {
        "$filter": "isRead eq false",
        "$select": "id,subject,from,toRecipients,body,receivedDateTime,isRead",
        "$orderby": "receivedDateTime desc",
        "$top": str(top or settings.outlook_max_messages_per_poll),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f"{GRAPH_URL}/me/mailFolders/inbox/messages",
            headers=_auth_headers(access_token),
            params=params,
        )
        response.raise_for_status()
        messages: list[dict[str, Any]] = response.json().get("value", [])
        return messages


async def mark_as_read(access_token: str, message_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.patch(
            f"{GRAPH_URL}/me/messages/{message_id}",
            headers={**_auth_headers(access_token), "Content-Type": "application/json"},
            json={"isRead": True},
        )
        response.raise_for_status()


def _plain_text_to_html(text: str) -> str:
    """Graph inserts `comment` into an HTML body, where a raw \\n is just
    collapsed whitespace -- hence the reply arriving as one paragraph.
    Escape first, since the text is an LLM reply to untrusted email content,
    then turn newlines into line breaks.
    """
    return html.escape(text).replace("\n", "<br>")


async def send_reply(access_token: str, message_id: str, reply_body: str) -> None:
    """Reply to a message in its own thread.

    /reply rather than composing a fresh message so the patient sees the reply
    threaded under what they sent, and so Graph fills in recipient and subject
    from the original.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f"{GRAPH_URL}/me/messages/{message_id}/reply",
            headers={**_auth_headers(access_token), "Content-Type": "application/json"},
            json={"comment": _plain_text_to_html(reply_body)},
        )
        response.raise_for_status()

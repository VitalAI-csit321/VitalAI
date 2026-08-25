"""Graph message parsing and transport contract.

Every case here is a real defect found while porting Matthew's
Inbox_Handling/Email_Parser.py, plus the request shapes his Outlook_Reader.py
established. No live Graph calls: transport is exercised through
httpx.MockTransport.
"""

import httpx
import pytest

from app.schemas.email import EmailIngestRequest
from app.services import outlook_client
from app.services.outlook_client import (
    GRAPH_URL,
    strip_html,
    to_ingest_request,
)


def _message(**overrides) -> dict:
    base = {
        "id": "AAMkAGI2",
        "subject": "Repeat prescription",
        "from": {"emailAddress": {"address": "patient@example.com"}},
        "toRecipients": [{"emailAddress": {"address": "clinic@example.com"}}],
        "body": {"contentType": "html", "content": "<p>Please renew my script.</p>"},
        "receivedDateTime": "2026-08-20T09:15:00Z",
    }
    base.update(overrides)
    return base


class TestStripHtml:
    def test_style_block_contents_are_removed(self):
        """The ported regex stripped tags but left CSS text behind, which real
        Outlook mail carries in bulk and which would reach the classifier."""
        raw = "<style>.x{color:red;font-size:12px}</style><p>Hello there</p>"
        assert strip_html(raw) == "Hello there"

    def test_script_block_contents_are_removed(self):
        raw = "<script>var a = 1;</script><p>Hello</p>"
        assert strip_html(raw) == "Hello"

    def test_entities_are_unescaped(self):
        # &nbsp; unescapes to \xa0, which the whitespace collapse then folds
        # into a normal space. Both steps are wanted: the classifier should see
        # ordinary prose, not entity soup or non-breaking spaces.
        assert strip_html("<p>Tom &amp; Jerry&nbsp;here</p>") == "Tom & Jerry here"

    def test_whitespace_is_collapsed(self):
        assert strip_html("<p>a</p>\n\n   <p>b</p>") == "a b"

    def test_empty_and_none_are_safe(self):
        assert strip_html(None) == ""
        assert strip_html("") == ""


class TestToIngestRequest:
    def test_maps_a_normal_message(self):
        request = to_ingest_request(_message())
        assert isinstance(request, EmailIngestRequest)
        assert request.sender == "patient@example.com"
        assert request.recipient == "clinic@example.com"
        assert request.subject == "Repeat prescription"
        assert request.body == "Please renew my script."
        assert request.external_id == "AAMkAGI2"
        assert request.external_source == "outlook"
        assert request.received_at is not None
        assert request.received_at.year == 2026

    def test_blank_subject_gets_a_placeholder(self):
        """EmailIngestRequest enforces min_length=1, so a legitimately blank
        subject would otherwise fail validation and 422 the whole message."""
        request = to_ingest_request(_message(subject=""))
        assert request is not None
        assert request.subject == "(no subject)"

    def test_missing_subject_key_gets_a_placeholder(self):
        message = _message()
        del message["subject"]
        request = to_ingest_request(message)
        assert request is not None
        assert request.subject == "(no subject)"

    def test_missing_recipients_falls_back_to_configured_mailbox(self, monkeypatch):
        monkeypatch.setattr(
            outlook_client.settings, "outlook_mailbox_address", "shared@example.com"
        )
        request = to_ingest_request(_message(toRecipients=[]))
        assert request is not None
        assert request.recipient == "shared@example.com"

    def test_missing_recipients_without_config_falls_back_to_sender(self, monkeypatch):
        monkeypatch.setattr(outlook_client.settings, "outlook_mailbox_address", "")
        request = to_ingest_request(_message(toRecipients=[]))
        assert request is not None
        assert request.recipient == "patient@example.com"

    def test_empty_body_is_skipped_not_raised(self):
        """A style-only body strips to nothing; returning None keeps one bad
        message from aborting the whole poll cycle."""
        assert to_ingest_request(_message(body={"content": "<style>.a{}</style>"})) is None

    def test_missing_id_is_skipped(self):
        message = _message()
        del message["id"]
        assert to_ingest_request(message) is None

    def test_missing_sender_is_skipped(self):
        assert to_ingest_request(_message(**{"from": {}})) is None

    def test_unparseable_timestamp_does_not_fail_the_message(self):
        request = to_ingest_request(_message(receivedDateTime="not-a-date"))
        assert request is not None
        assert request.received_at is None

    def test_overlong_subject_is_truncated_to_column_width(self):
        request = to_ingest_request(_message(subject="x" * 600))
        assert request is not None
        assert len(request.subject) == 500


class TestTransport:
    @pytest.mark.asyncio
    async def test_get_unread_emails_sends_matthews_query(self, monkeypatch):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"value": [_message()]})

        _patch_transport(monkeypatch, handler)
        messages = await outlook_client.get_unread_emails("tok", top=25)

        assert len(messages) == 1
        assert f"{GRAPH_URL}/me/mailFolders/inbox/messages" in captured["url"]
        assert "isRead+eq+false" in captured["url"] or "isRead%20eq%20false" in captured["url"]
        assert "toRecipients" in captured["url"]
        assert "%24top=25" in captured["url"]
        assert captured["auth"] == "Bearer tok"

    @pytest.mark.asyncio
    async def test_mark_as_read_patches_is_read(self, monkeypatch):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["body"] = request.content
            return httpx.Response(200, json={})

        _patch_transport(monkeypatch, handler)
        await outlook_client.mark_as_read("tok", "AAMkAGI2")

        assert captured["method"] == "PATCH"
        assert b'"isRead": true' in captured["body"] or b'"isRead":true' in captured["body"]

    @pytest.mark.asyncio
    async def test_send_reply_posts_to_reply_endpoint(self, monkeypatch):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content
            return httpx.Response(202)

        _patch_transport(monkeypatch, handler)
        await outlook_client.send_reply("tok", "AAMkAGI2", "Thanks, booked.")

        assert captured["url"].endswith("/me/messages/AAMkAGI2/reply")
        assert b"Thanks, booked." in captured["body"]

    @pytest.mark.asyncio
    async def test_graph_error_propagates(self, monkeypatch):
        """Callers distinguish a failed send from a successful one, so a 4xx
        must raise rather than be swallowed here."""
        _patch_transport(monkeypatch, lambda request: httpx.Response(403, json={}))
        with pytest.raises(httpx.HTTPStatusError):
            await outlook_client.send_reply("tok", "AAMkAGI2", "body")


def _patch_transport(monkeypatch, handler) -> None:
    """Route every AsyncClient in outlook_client through a mock transport."""
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(outlook_client.httpx, "AsyncClient", factory)

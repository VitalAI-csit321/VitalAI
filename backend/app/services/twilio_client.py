"""Twilio: request signatures, and the one recording per voicemail that is
downloaded then deleted (voicemail spec §11, privacy APP 8)."""

from __future__ import annotations

import re
from collections.abc import Mapping

import httpx
from twilio.request_validator import RequestValidator

from app.config import settings

_RECORDING = "https://api.twilio.com/2010-04-01/Accounts/{account}/Recordings/{recording}{suffix}"
_RECORDING_SID = re.compile(r"RE[0-9a-f]{32}")


def valid_signature(path: str, params: Mapping[str, str], signature: str) -> bool:
    url = settings.twilio_webhook_base_url.rstrip("/") + path
    validator = RequestValidator(settings.twilio_auth_token)
    return bool(validator.validate(url, dict(params), signature))


def _recording_url(recording_sid: str, suffix: str) -> str:
    """Built from our account and a validated sid. Never the RecordingUrl a
    request carries, so no request can point the server at another host."""
    if not _RECORDING_SID.fullmatch(recording_sid):
        raise ValueError("not a Twilio recording sid")
    return _RECORDING.format(
        account=settings.twilio_account_sid, recording=recording_sid, suffix=suffix
    )


def _auth() -> tuple[str, str]:
    return settings.twilio_account_sid, settings.twilio_auth_token


async def download_recording(recording_sid: str) -> bytes:
    async with httpx.AsyncClient(timeout=30, auth=_auth()) as client:
        response = await client.get(_recording_url(recording_sid, ".wav"))
        response.raise_for_status()
        return response.content


async def delete_recording(recording_sid: str) -> bool:
    """True when Twilio no longer holds it (404 counts: already gone)."""
    try:
        async with httpx.AsyncClient(timeout=15, auth=_auth()) as client:
            response = await client.delete(_recording_url(recording_sid, ".json"))
    except httpx.HTTPError:
        return False
    return response.status_code in (204, 404)

"""The conftest safety net against real model calls from tests (spec G.3).

Five modules import get_llm under their own name (rag/answer.py, routes/llm.py,
call_service.py, email_service.py, inbox_service.py), so patching one of them
leaves four doors open. The net blocks the shared client's own network door
instead: building a client stays legal, calling one raises.
"""

import pytest

from app.config import settings
from app.llm.provider import get_llm


def _fresh_client():
    """A real client, built the way the app builds it."""
    get_llm.cache_clear()
    try:
        return get_llm()
    finally:
        # Never leave a real client in the process-wide lru_cache.
        get_llm.cache_clear()


async def test_awaiting_the_real_client_raises():
    llm = _fresh_client()
    with pytest.raises(RuntimeError, match="real LLM"):
        await llm.ainvoke("are you there?")


def test_calling_the_real_client_synchronously_raises():
    llm = _fresh_client()
    with pytest.raises(RuntimeError, match="real LLM"):
        llm.invoke("are you there?")


def test_building_the_real_client_is_still_allowed():
    """test_llm.py builds a client and never calls it; that must keep passing."""
    assert _fresh_client() is not None


def test_outlook_and_auto_send_are_pinned_whatever_the_environment_says():
    """A developer's .env (or an exported shell variable) must not be able to
    change what the suite tests. conftest sets both before app.config loads."""
    assert settings.outlook_enabled is False
    assert settings.email_auto_send_enabled is True

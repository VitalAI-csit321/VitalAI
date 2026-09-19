"""Alembic's env.py must not silence the loggers the rest of the suite reads.

conftest runs `alembic upgrade head` on the Postgres track. That executes
alembic/env.py, which calls logging.config.fileConfig(). fileConfig defaults to
disable_existing_loggers=True, which sets .disabled on every logger created
before it ran -- that is, on every module-level logging.getLogger(__name__) in
the app. caplog then reads empty for the rest of the pytest session, and a test
asserting on a log line fails looking exactly like the code under test never
ran. That cost a debugging session once (see commit f78d7cc, which had to
rewrite a test around the symptom before the cause was found).

env.py passes disable_existing_loggers=False. This fails if that is removed.
"""

import logging

import pytest

# Created at import time -- i.e. at collection, before any fixture runs. This is
# exactly the shape of logger fileConfig() would silence.
_IMPORT_TIME_LOGGER = logging.getLogger("app.services.email_service")


async def test_alembic_upgrade_leaves_import_time_loggers_enabled(test_engine):
    if test_engine.dialect.name != "postgresql":
        pytest.skip("alembic/env.py only runs on the Postgres track")

    assert _IMPORT_TIME_LOGGER.disabled is False, (
        "alembic/env.py's fileConfig() disabled an existing logger. "
        "Pass disable_existing_loggers=False."
    )

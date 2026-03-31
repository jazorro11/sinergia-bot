"""Set required env vars before any import of `bot` (config exits on missing vars)."""

from __future__ import annotations

import json
import os

import pytest
from unittest.mock import patch

_GOOGLE_SA = {
    "type": "service_account",
    "project_id": "pytest",
    "private_key_id": "pytest",
    "private_key": (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA0pytest0\n"
        "-----END RSA PRIVATE KEY-----\n"
    ),
    "client_email": "pytest@pytest.iam.gserviceaccount.com",
    "client_id": "1",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}

_DEFAULTS: dict[str, str] = {
    "TELEGRAM_BOT_TOKEN": "test-token",
    "OPENAI_API_KEY": "sk-test",
    "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(_GOOGLE_SA),
    "GOOGLE_SHEET_ID": "test-sheet-id",
    "CALENDLY_URL": "https://calendly.com/test/event",
    "LLM_MODEL": "gpt-4o",
    "LLM_EXTRACTION_MODEL": "gpt-4o-mini",
    "EXTRACTION_FREQUENCY": "2",
    "PORT": "8000",
    "LOG_LEVEL": "INFO",
}

for _key, _val in _DEFAULTS.items():
    os.environ[_key] = _val


@pytest.fixture(autouse=True)
def _conversation_not_silence_hours() -> None:
    """Real wall-clock may fall in 22:00–07:00 Colombia; most tests need the normal flow."""
    with patch("bot.conversation.is_silence_hours", return_value=False):
        yield

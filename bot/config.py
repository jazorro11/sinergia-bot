"""Environment, external clients, and business constants. Sole reader of os.environ (except LOG_LEVEL in logger)."""

from __future__ import annotations

import json
import os
import sys
from datetime import timedelta, timezone

from openai import OpenAI

from bot.logger import get_logger

logger = get_logger(__name__)


def _fail_missing(name: str) -> None:
    logger.critical("Missing required environment variable: %s", name)
    sys.exit(1)


def _require_str(name: str) -> str:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        _fail_missing(name)
    return str(raw).strip()


def _parse_google_service_account_json(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.critical("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: %s", e)
        sys.exit(1)
    if not isinstance(data, dict):
        logger.critical("GOOGLE_SERVICE_ACCOUNT_JSON must be a JSON object")
        sys.exit(1)
    return data


def _parse_extraction_frequency() -> int:
    raw = os.environ.get("EXTRACTION_FREQUENCY", "1").strip()
    try:
        n = int(raw)
    except ValueError:
        logger.critical("EXTRACTION_FREQUENCY must be an integer, got: %r", raw)
        sys.exit(1)
    if n < 1:
        logger.critical("EXTRACTION_FREQUENCY must be >= 1, got: %s", n)
        sys.exit(1)
    return n


def _parse_port() -> int:
    raw = os.environ.get("PORT", "8000").strip()
    try:
        return int(raw)
    except ValueError:
        logger.critical("PORT must be an integer, got: %r", raw)
        sys.exit(1)


def _parse_post_calendly_farewell_user_messages() -> int:
    raw = os.environ.get("POST_CALENDLY_FAREWELL_USER_MESSAGES", "2").strip()
    try:
        n = int(raw)
    except ValueError:
        logger.critical(
            "POST_CALENDLY_FAREWELL_USER_MESSAGES must be an integer, got: %r", raw
        )
        sys.exit(1)
    if n < 0:
        logger.critical(
            "POST_CALENDLY_FAREWELL_USER_MESSAGES must be >= 0, got: %s", n
        )
        sys.exit(1)
    return n


# --- Required ---
TELEGRAM_BOT_TOKEN = _require_str("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = _require_str("OPENAI_API_KEY")
GOOGLE_SERVICE_ACCOUNT_CREDENTIALS = _parse_google_service_account_json(
    _require_str("GOOGLE_SERVICE_ACCOUNT_JSON")
)
GOOGLE_SHEET_ID = _require_str("GOOGLE_SHEET_ID")
CALENDLY_URL = _require_str("CALENDLY_URL")
LLM_MODEL = _require_str("LLM_MODEL")
LLM_EXTRACTION_MODEL = _require_str("LLM_EXTRACTION_MODEL")

# --- Optional ---
EXTRACTION_FREQUENCY = _parse_extraction_frequency()
PORT = _parse_port()
POST_CALENDLY_FAREWELL_USER_MESSAGES = _parse_post_calendly_farewell_user_messages()

# --- OpenAI (default API host; no base_url) ---
llm = OpenAI(api_key=OPENAI_API_KEY)
llm_extraction = OpenAI(api_key=OPENAI_API_KEY)

# --- Silence window (Colombia UTC-5, no DST); logic lives in conversation.py ---
BUSINESS_TZ = timezone(timedelta(hours=-5))
SILENCE_START_HOUR = 22
SILENCE_END_HOUR = 7

USER_MESSAGE_LIMIT = 30
RESPONSE_DELAY_MS = 1000

MSG_SILENCE_ABSENCE = (
    "Hola! En este momento no estoy disponible, pero mañana en la mañana te respondo 😌"
)
MSG_CLOSED_CALENDLY_OR_LIMIT_TEMPLATE = (
    "Hola! Ya estamos al tanto de tu proyecto. Si necesitas algo adicional, "
    "escríbenos por acá: {calendly_url}"
)
MSG_CLOSED_NO_AGENDAR = (
    "Hola! Ya estamos al tanto de tu proyecto. Alejandro se pondrá en contacto contigo pronto."
)
MSG_UNSUPPORTED_CONTENT = (
    "Por ahora solo puedo leer mensajes de texto. Si puedes, escríbeme lo que necesitas "
    "en un mensaje y con gusto te ayudo."
)
MSG_FALLBACK_SHEETS_HISTORY = "Disculpa, tuve un problema de agenda ¿Puedes repetir por favor?"
MSG_FALLBACK_LLM = (
    "Disculpa, tuve un problema y no me muestra los últimos mensajes ¿Puedes repetir por favor?"
)

logger.info(
    "Config loaded: LLM_MODEL=%s LLM_EXTRACTION_MODEL=%s EXTRACTION_FREQUENCY=%s "
    "POST_CALENDLY_FAREWELL_USER_MESSAGES=%s",
    LLM_MODEL,
    LLM_EXTRACTION_MODEL,
    EXTRACTION_FREQUENCY,
    POST_CALENDLY_FAREWELL_USER_MESSAGES,
)

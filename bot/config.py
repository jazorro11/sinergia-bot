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
    raw = os.environ.get("EXTRACTION_FREQUENCY", "2").strip()
    try:
        n = int(raw)
    except ValueError:
        logger.critical("EXTRACTION_FREQUENCY must be an integer, got: %r", raw)
        sys.exit(1)
    if n < 1:
        logger.critical("EXTRACTION_FREQUENCY must be >= 1, got: %s", n)
        sys.exit(1)
    return n


def _parse_conversation_history_max_messages() -> int:
    """0 = sin límite (enviar historial completo al LLM)."""
    raw = os.environ.get("CONVERSATION_HISTORY_MAX_MESSAGES", "0").strip()
    try:
        n = int(raw)
    except ValueError:
        logger.critical(
            "CONVERSATION_HISTORY_MAX_MESSAGES must be an integer, got: %r", raw
        )
        sys.exit(1)
    if n < 0:
        logger.critical(
            "CONVERSATION_HISTORY_MAX_MESSAGES must be >= 0, got: %s", n
        )
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


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    v = str(raw).strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    logger.critical("%s must be a boolean (true/false), got: %r", name, raw)
    sys.exit(1)


def _parse_non_negative_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        n = int(str(raw).strip())
    except ValueError:
        logger.critical("%s must be an integer, got: %r", name, raw)
        sys.exit(1)
    if n < 0:
        logger.critical("%s must be >= 0, got: %s", name, n)
        sys.exit(1)
    return n


def _parse_positive_int(name: str, default: int, *, minimum: int = 1) -> int:
    n = _parse_non_negative_int(name, default)
    if n < minimum:
        logger.critical("%s must be >= %s, got: %s", name, minimum, n)
        sys.exit(1)
    return n


def _parse_post_llm_delay_ms() -> int:
    """Delay tras respuesta del LLM antes de send_message (Telegram)."""
    raw = os.environ.get("POST_LLM_DELAY_MS")
    if raw is not None and str(raw).strip():
        try:
            n = int(str(raw).strip())
        except ValueError:
            logger.critical("POST_LLM_DELAY_MS must be an integer, got: %r", raw)
            sys.exit(1)
        if n < 0:
            logger.critical("POST_LLM_DELAY_MS must be >= 0, got: %s", n)
            sys.exit(1)
        return n
    return 1000


def _parse_message_debounce_join() -> str:
    raw = os.environ.get("MESSAGE_DEBOUNCE_JOIN")
    if raw is None or not str(raw).strip():
        return "\n\n"
    # Permitir secuencias escapadas típicas en .env
    return str(raw).strip().replace("\\n", "\n")


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
CONVERSATION_HISTORY_MAX_MESSAGES = _parse_conversation_history_max_messages()
PORT = _parse_port()
POST_CALENDLY_FAREWELL_USER_MESSAGES = _parse_post_calendly_farewell_user_messages()

# --- Telegram UX: typing indicator + acumulación de mensajes (webhook) ---
TELEGRAM_TYPING_ENABLED = _parse_bool("TELEGRAM_TYPING_ENABLED", False)
TYPING_RENEW_INTERVAL_SECONDS = _parse_positive_int(
    "TYPING_RENEW_INTERVAL_SECONDS", 4, minimum=1
)
MESSAGE_DEBOUNCE_SECONDS = _parse_non_negative_int("MESSAGE_DEBOUNCE_SECONDS", 0)
MESSAGE_DEBOUNCE_JOIN = _parse_message_debounce_join()
POST_LLM_DELAY_MS = _parse_post_llm_delay_ms()

# --- OpenAI (default API host; no base_url) ---
llm = OpenAI(api_key=OPENAI_API_KEY)
llm_extraction = OpenAI(api_key=OPENAI_API_KEY)

# --- Silence window (Colombia UTC-5, no DST); logic lives in conversation.py ---
BUSINESS_TZ = timezone(timedelta(hours=-5))
SILENCE_START_HOUR = 22
SILENCE_END_HOUR = 7

USER_MESSAGE_LIMIT = 30
# Alias del delay post-LLM (compatibilidad con código/docs que citen RESPONSE_DELAY_MS).
RESPONSE_DELAY_MS = POST_LLM_DELAY_MS

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
    "CONVERSATION_HISTORY_MAX_MESSAGES=%s POST_CALENDLY_FAREWELL_USER_MESSAGES=%s "
    "TELEGRAM_TYPING_ENABLED=%s MESSAGE_DEBOUNCE_SECONDS=%s POST_LLM_DELAY_MS=%s",
    LLM_MODEL,
    LLM_EXTRACTION_MODEL,
    EXTRACTION_FREQUENCY,
    CONVERSATION_HISTORY_MAX_MESSAGES,
    POST_CALENDLY_FAREWELL_USER_MESSAGES,
    TELEGRAM_TYPING_ENABLED,
    MESSAGE_DEBOUNCE_SECONDS,
    POST_LLM_DELAY_MS,
)

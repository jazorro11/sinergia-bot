"""Orquesta el flujo de un mensaje: restricciones, LLM, extracción y persistencia."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from bot import config, extraction, storage
from bot.logger import get_logger
from bot.prompts import SYSTEM_PROMPT

logger = get_logger(__name__)

# Despedida al alcanzar el límite de mensajes (brief v4: Calendly + contacto si no agenda).
_MSG_USER_LIMIT_FAREWELL = (
    "Llegamos al límite de mensajes en esta conversación. Para agendar con Alejandro usa este enlace: "
    "{calendly_url}. Si no agendas ahora, él se pondrá en contacto contigo pronto."
)


def is_silence_hours() -> bool:
    now = datetime.now(config.BUSINESS_TZ)
    h = now.hour
    return h >= config.SILENCE_START_HOUR or h < config.SILENCE_END_HOUR


def count_user_messages(history: list[dict[str, Any]]) -> int:
    return sum(1 for m in history if m.get("role") == "user")


def should_extract(user_message_count: int) -> bool:
    return user_message_count % config.EXTRACTION_FREQUENCY == 0


def _norm_cid(chat_id: str | int) -> str:
    return str(chat_id).strip()


def _history_plus_user(
    history: list[dict[str, str]], text: str
) -> list[dict[str, str]]:
    return [*history, {"role": "user", "content": text}]


def _lead_row_complete(lead: dict[str, Any]) -> bool:
    for key in storage.LEAD_DATA_KEYS:
        v = lead.get(key)
        if v is None or str(v).strip() == "":
            return False
    return True


def _lead_mapping_from_row(lead: dict[str, Any]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for k in storage.LEAD_DATA_KEYS:
        v = lead.get(k)
        if v is None:
            out[k] = None
            continue
        s = str(v).strip()
        out[k] = s if s else None
    return out


def process_message(
    chat_id: str | int,
    user_id: str | int,
    text: str,
    timestamp: int,
    is_edited: bool,
) -> str:
    cid = _norm_cid(chat_id)
    if is_edited:
        logger.debug("Mensaje editado: chat_id=%s user_id=%s", cid, user_id)

    if is_silence_hours():
        logger.info("Silencio nocturno: chat_id=%s", cid)
        return config.MSG_SILENCE_ABSENCE

    lead_closed: dict[str, Any] | None = None
    try:
        lead_closed = storage.get_lead(cid)
    except Exception:
        logger.exception("Error get_lead (asumiendo en_curso): chat_id=%s", cid)

    if lead_closed:
        est = str(lead_closed.get("estado", "")).strip()
        if est in ("calendly_enviado", "limite_alcanzado"):
            logger.info("Conversación cerrada, mensaje fijo: chat_id=%s", cid)
            return config.MSG_CLOSED_CALENDLY_OR_LIMIT_TEMPLATE.format(
                calendly_url=config.CALENDLY_URL
            )
        if est == "no_agendar":
            logger.info("Conversación cerrada, mensaje fijo: chat_id=%s", cid)
            return config.MSG_CLOSED_NO_AGENDAR

    try:
        history = storage.get_conversation_history(cid)
    except Exception:
        logger.exception("Error leyendo historial: chat_id=%s", cid)
        return config.MSG_FALLBACK_SHEETS_HISTORY

    user_count_in_sheet = count_user_messages(history)
    if user_count_in_sheet >= config.USER_MESSAGE_LIMIT:
        final = extraction.extract_lead_data(history, cid)
        storage.upsert_lead(
            cid, final.model_dump() if final else {}, estado="limite_alcanzado"
        )
        storage.mark_conversation_closed(cid)
        logger.warning(
            "Límite alcanzado: chat_id=%s, mensajes=%s",
            cid,
            config.USER_MESSAGE_LIMIT,
        )
        return _MSG_USER_LIMIT_FAREWELL.format(calendly_url=config.CALENDLY_URL)

    system_content = SYSTEM_PROMPT.replace("{calendly_url}", config.CALENDLY_URL)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_content},
        *[{"role": str(m["role"]), "content": str(m["content"])} for m in history],
        {"role": "user", "content": text},
    ]
    full_history = _history_plus_user(history, text)

    logger.debug(
        "LLM conversacional: chat_id=%s turnos_historial=%s",
        cid,
        len(history),
    )

    try:
        response = config.llm.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
            temperature=0.7,
        )
        raw = response.choices[0].message.content
        if raw is None or not str(raw).strip():
            logger.error("LLM conversacional: respuesta vacía chat_id=%s", cid)
            return config.MSG_FALLBACK_LLM
        assistant_text = str(raw).strip()
    except Exception:
        logger.exception("LLM conversacional falló: chat_id=%s", cid)
        return config.MSG_FALLBACK_LLM

    closed_via_calendly_in_response = False
    if config.CALENDLY_URL in assistant_text:
        rec = extraction.extract_lead_data(full_history, cid)
        storage.upsert_lead(
            cid, rec.model_dump() if rec else {}, estado="calendly_enviado"
        )
        storage.mark_conversation_closed(cid)
        logger.info("Calendly detectado en respuesta LLM: chat_id=%s", cid)
        closed_via_calendly_in_response = True

    periodic_extraction_done = False
    if not closed_via_calendly_in_response:
        total_user = count_user_messages(history) + 1
        if should_extract(total_user):
            periodic_extraction_done = True
            rec_p = extraction.extract_lead_data(full_history, cid)
            if rec_p is not None:
                storage.upsert_lead(cid, rec_p.model_dump())
        else:
            logger.debug(
                "Extracción periódica no aplica: chat_id=%s user_total=%s frecuencia=%s",
                cid,
                total_user,
                config.EXTRACTION_FREQUENCY,
            )

    conversation_closed = closed_via_calendly_in_response
    if periodic_extraction_done and not closed_via_calendly_in_response:
        try:
            lead_after = storage.get_lead(cid)
        except Exception:
            logger.exception("Error get_lead post-extracción: chat_id=%s", cid)
            lead_after = None
        if lead_after and _lead_row_complete(lead_after):
            storage.upsert_lead(
                cid, _lead_mapping_from_row(lead_after), estado="calendly_enviado"
            )
            storage.mark_conversation_closed(cid)
            logger.info("Calendly enviado: chat_id=%s, campos_completos=9/9", cid)
            conversation_closed = True

    estado_turno = "cerrada" if conversation_closed else "en_curso"
    storage.save_conversation_turn(cid, "user", text, timestamp, estado_turno)
    storage.save_conversation_turn(
        cid, "assistant", assistant_text, int(time.time()), estado_turno
    )

    return assistant_text

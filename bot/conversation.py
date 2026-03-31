"""Orquesta el flujo de un mensaje: restricciones, LLM, extracción y persistencia."""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from bot import config, extraction, storage
from bot.logger import get_logger
from bot.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_POST_CALENDLY_FAREWELL

logger = get_logger(__name__)

# Despedida al alcanzar el límite de mensajes (brief v4: Calendly + contacto si no agenda).
_MSG_USER_LIMIT_FAREWELL = (
    "Llegamos al límite de mensajes en esta conversación. Para agendar con Alejandro usa este enlace: "
    "{calendly_url}. Si no agendas ahora, él se pondrá en contacto contigo pronto."
)

# Cierre con Calendly: 9 campos completos o los tres mínimos del brief.
_MIN_CALENDLY_KEYS = ("nombre", "ciudad", "area_aprox")
_MISSING_MIN_LABELS: dict[str, str] = {
    "nombre": "tu nombre",
    "ciudad": "la ciudad o municipio del proyecto",
    "area_aprox": "el área aproximada en m²",
}
_MSG_UPSERT_FAILED = (
    "No pude guardar tus datos en este momento (fallo técnico). "
    "¿Me escribes de nuevo en unos minutos? Cuando funcione te paso el enlace para agendar."
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


def _merge_lead_for_gate(
    existing: dict[str, Any] | None,
    rec: extraction.LeadRecord | None,
) -> dict[str, str]:
    """Unión extracción + fila en Sheets: prioriza valor nuevo de extracción si existe."""
    merged: dict[str, str] = {}
    for k in storage.LEAD_DATA_KEYS:
        from_sheet = ""
        if existing:
            v = existing.get(k)
            if v is not None and str(v).strip():
                from_sheet = str(v).strip()
        from_ext = ""
        if rec is not None:
            raw = rec.model_dump().get(k)
            if raw is not None and str(raw).strip():
                from_ext = str(raw).strip()
        merged[k] = from_ext or from_sheet
    return merged


def _merged_to_lead_payload(merged: dict[str, str]) -> dict[str, str | None]:
    return {k: (v if (v := merged.get(k, "").strip()) else None) for k in storage.LEAD_DATA_KEYS}


def _can_close_with_calendly(merged: dict[str, str]) -> bool:
    if all(merged.get(k, "").strip() for k in storage.LEAD_DATA_KEYS):
        return True
    return all(merged.get(k, "").strip() for k in _MIN_CALENDLY_KEYS)


def _missing_minimum_phrases(merged: dict[str, str]) -> list[str]:
    return [
        _MISSING_MIN_LABELS[k]
        for k in _MIN_CALENDLY_KEYS
        if not merged.get(k, "").strip()
    ]


def _message_ask_missing_minimum(phrases: list[str]) -> str:
    if not phrases:
        return "Antes del enlace necesito un dato más. ¿Me lo compartes?"
    if len(phrases) == 1:
        return f"Antes de pasarte el enlace necesito {phrases[0]}. ¿Me lo compartes?"
    if len(phrases) == 2:
        return (
            f"Antes del enlace me faltan {phrases[0]} y {phrases[1]}. ¿Me los compartes?"
        )
    return (
        f"Antes del enlace me faltan {phrases[0]}, {phrases[1]} y {phrases[2]}. "
        "¿Me los compartes?"
    )


def _strip_calendly_from_text(text: str) -> str:
    t = text.replace(config.CALENDLY_URL, "").strip()
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def _history_last_assistant_had_calendly(
    history: list[dict[str, Any]], url: str
) -> bool:
    for m in reversed(history):
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        return content is not None and url in str(content)
    return False


def _index_last_assistant_with_calendly(
    history: list[dict[str, Any]], url: str
) -> int | None:
    for i in range(len(history) - 1, -1, -1):
        m = history[i]
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if content is not None and url in str(content):
            return i
    return None


def _count_user_messages_after_index(history: list[dict[str, Any]], idx: int) -> int:
    return sum(
        1
        for j in range(idx + 1, len(history))
        if history[j].get("role") == "user"
    )


def _post_calendly_farewell_allowed(
    history: list[dict[str, Any]], url: str, limit: int
) -> bool:
    if limit <= 0:
        return False
    cal_idx = _index_last_assistant_with_calendly(history, url)
    if cal_idx is None:
        return False
    users_after = _count_user_messages_after_index(history, cal_idx)
    effective = users_after + 1
    return effective <= limit


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

    existing_lead: dict[str, Any] | None = None
    try:
        existing_lead = storage.get_lead(cid)
    except Exception:
        logger.exception("Error get_lead (asumiendo en_curso): chat_id=%s", cid)

    if existing_lead:
        est = str(existing_lead.get("estado", "")).strip()
        if est == "no_agendar":
            logger.info("Conversación cerrada, mensaje fijo: chat_id=%s", cid)
            return config.MSG_CLOSED_NO_AGENDAR

    try:
        history = storage.get_conversation_history(cid)
    except Exception:
        logger.exception("Error leyendo historial: chat_id=%s", cid)
        return config.MSG_FALLBACK_SHEETS_HISTORY

    est = str(existing_lead.get("estado", "")).strip() if existing_lead else ""
    closed_calendly_like = est in ("calendly_enviado", "limite_alcanzado") or (
        existing_lead is None
        and _history_last_assistant_had_calendly(history, config.CALENDLY_URL)
    )

    if closed_calendly_like:
        if _post_calendly_farewell_allowed(
            history,
            config.CALENDLY_URL,
            config.POST_CALENDLY_FAREWELL_USER_MESSAGES,
        ):
            logger.info("Despedida post-Calendly (LLM): chat_id=%s", cid)
            hist_norm: list[dict[str, str]] = [
                {"role": str(m["role"]), "content": str(m["content"])}
                for m in history
            ]
            messages_fw: list[dict[str, str]] = [
                {"role": "system", "content": SYSTEM_PROMPT_POST_CALENDLY_FAREWELL},
                *hist_norm,
                {"role": "user", "content": text},
            ]
            try:
                response = config.llm.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=messages_fw,
                    temperature=0.7,
                )
                raw_fw = response.choices[0].message.content
                if raw_fw is None or not str(raw_fw).strip():
                    logger.error("LLM despedida: respuesta vacía chat_id=%s", cid)
                    assistant_text = config.MSG_FALLBACK_LLM
                else:
                    assistant_text = _strip_calendly_from_text(str(raw_fw).strip())
            except Exception:
                logger.exception("LLM despedida falló: chat_id=%s", cid)
                assistant_text = config.MSG_FALLBACK_LLM

            storage.save_conversation_turn(cid, "user", text, timestamp, "cerrada")
            storage.save_conversation_turn(
                cid, "assistant", assistant_text, int(time.time()), "cerrada"
            )
            return assistant_text

        logger.info("Conversación cerrada, mensaje fijo: chat_id=%s", cid)
        return config.MSG_CLOSED_CALENDLY_OR_LIMIT_TEMPLATE.format(
            calendly_url=config.CALENDLY_URL
        )

    user_count_in_sheet = count_user_messages(history)
    if user_count_in_sheet >= config.USER_MESSAGE_LIMIT:
        final = extraction.extract_lead_data(history, cid)
        ok_limit = storage.upsert_lead(
            cid, final.model_dump() if final else {}, estado="limite_alcanzado"
        )
        if not ok_limit:
            logger.error("Límite: upsert falló, chat_id=%s", cid)
            return _MSG_UPSERT_FAILED
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
        rec_close = extraction.extract_lead_data(full_history, cid)
        merged = _merge_lead_for_gate(existing_lead, rec_close)
        if not _can_close_with_calendly(merged):
            stripped = _strip_calendly_from_text(assistant_text)
            ask = _message_ask_missing_minimum(_missing_minimum_phrases(merged))
            assistant_text = f"{stripped}\n\n{ask}".strip() if stripped else ask
            logger.info(
                "Calendly en respuesta bloqueado (faltan mínimos o 9 campos): chat_id=%s",
                cid,
            )
        else:
            payload = _merged_to_lead_payload(merged)
            ok_cal = storage.upsert_lead(
                cid, payload, estado="calendly_enviado"
            )
            if ok_cal:
                storage.mark_conversation_closed(cid)
                logger.info("Calendly detectado en respuesta LLM: chat_id=%s", cid)
                closed_via_calendly_in_response = True
            else:
                assistant_text = _strip_calendly_from_text(assistant_text)
                assistant_text = (
                    f"{assistant_text}\n\n{_MSG_UPSERT_FAILED}".strip()
                    if assistant_text
                    else _MSG_UPSERT_FAILED
                )
                logger.error(
                    "Calendly: upsert falló, no se cierra conversación: chat_id=%s", cid
                )

    periodic_extraction_done = False
    if not closed_via_calendly_in_response:
        total_user = count_user_messages(history) + 1
        if should_extract(total_user):
            periodic_extraction_done = True
            rec_p = extraction.extract_lead_data(full_history, cid)
            if rec_p is not None:
                _ = storage.upsert_lead(cid, rec_p.model_dump())
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
            ok_complete = storage.upsert_lead(
                cid, _lead_mapping_from_row(lead_after), estado="calendly_enviado"
            )
            if ok_complete:
                storage.mark_conversation_closed(cid)
                logger.info("Calendly enviado: chat_id=%s, campos_completos=9/9", cid)
                conversation_closed = True
            else:
                logger.error(
                    "Cierre 9/9: upsert falló, chat_id=%s", cid
                )

    estado_turno = "cerrada" if conversation_closed else "en_curso"
    storage.save_conversation_turn(cid, "user", text, timestamp, estado_turno)
    storage.save_conversation_turn(
        cid, "assistant", assistant_text, int(time.time()), estado_turno
    )

    return assistant_text

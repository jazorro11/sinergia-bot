"""Structured lead extraction via OpenAI; no Sheets or Telegram."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from bot import config, storage
from bot.logger import get_logger
from bot.prompts import EXTRACTION_PROMPT

logger = get_logger(__name__)

_MERGE_FROM_ROW_INSTRUCTION = """Registro previo del lead en el sistema (puede incluir datos de mensajes no incluidos en el historial abajo).
Para cada campo del JSON de salida: si el cliente lo menciona en el historial, extrae solo de ahí; si no aparece en el historial pero tiene valor en el registro previo, usa ese valor; si no hay ninguna fuente, null.
No inventes datos que no estén en el historial ni en el registro previo.

Registro previo:
"""


class LeadRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str | None = None
    ciudad: str | None = None
    tipo_espacio: str | None = None
    tipo_intervencion: str | None = None
    area_aprox: str | None = None
    situacion_actual: str | None = None
    fecha_deseada: str | None = None
    presupuesto: str | None = None
    alcance: str | None = None


def _history_to_messages(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for turn in history:
        role = turn.get("role")
        content = turn.get("content")
        if role not in ("user", "assistant"):
            continue
        if content is None:
            continue
        out.append({"role": role, "content": str(content)})
    return out


def _fields_with_value(record: LeadRecord) -> list[str]:
    return [name for name, val in record.model_dump().items() if val is not None and str(val).strip() != ""]


def _lead_record_json_schema_for_openai() -> dict[str, Any]:
    """OpenAI strict mode requires every property key in `required`."""
    schema = LeadRecord.model_json_schema()
    props = schema.get("properties")
    if isinstance(props, dict):
        schema["required"] = list(props.keys())
    return schema


def _merge_hint_from_lead_row(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    lines: list[str] = []
    for k in storage.LEAD_DATA_KEYS:
        v = row.get(k)
        if v is None or str(v).strip() == "":
            continue
        lines.append(f"{k}: {str(v).strip()}")
    if not lines:
        return None
    return _MERGE_FROM_ROW_INSTRUCTION + "\n".join(lines)


def extract_lead_data(
    history: list[dict[str, Any]],
    chat_id: str | int,
    *,
    merge_from_lead_row: dict[str, Any] | None = None,
) -> LeadRecord | None:
    system_content = EXTRACTION_PROMPT
    hint = _merge_hint_from_lead_row(merge_from_lead_row)
    if hint:
        system_content = f"{EXTRACTION_PROMPT}\n\n{hint}"

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_content},
        *_history_to_messages(history),
    ]
    cid = str(chat_id).strip()
    try:
        response = config.llm_extraction.chat.completions.create(
            model=config.LLM_EXTRACTION_MODEL,
            messages=messages,
            temperature=0.0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "lead_record",
                    "strict": True,
                    "schema": _lead_record_json_schema_for_openai(),
                },
            },
        )
        raw = response.choices[0].message.content
        if raw is None or not str(raw).strip():
            logger.error("Error extracción: chat_id=%s, error=empty response content", cid)
            return None
        record = LeadRecord.model_validate_json(raw)
        filled = _fields_with_value(record)
        logger.info("Extracción OK: chat_id=%s campos_con_valor=%s", cid, filled)
        return record
    except Exception as e:
        logger.error("Error extracción: chat_id=%s, error=%s", cid, e)
        return None

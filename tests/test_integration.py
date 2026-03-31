"""End-to-end style test with in-memory storage and mocked LLMs."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from bot import config
from bot.conversation import process_message
from bot.extraction import LeadRecord
from bot.storage import LEAD_DATA_KEYS


def _conv_completion(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_conversation_full_progression_calendly_close() -> None:
    cid = "9001"
    user_lines = [
        "Soy Luis",
        "Soy de Medellín",
        "Es una casa",
        "Quiero remodelación",
        "Como 80 metros",
        "Está muy deteriorada",
        "Para junio si se puede",
        "Tengo unos 50 millones",
        "Alcance: cocina y baños",
    ]
    progressive = [
        LeadRecord(nombre="Luis"),
        LeadRecord(ciudad="Medellín"),
        LeadRecord(tipo_espacio="Casa"),
        LeadRecord(tipo_intervencion="Remodelación"),
        LeadRecord(area_aprox="80 metros"),
        LeadRecord(situacion_actual="Muy deteriorada"),
        LeadRecord(fecha_deseada="Junio"),
        LeadRecord(presupuesto="50 millones"),
    ]
    final_record = LeadRecord(
        nombre="Luis",
        ciudad="Medellín",
        tipo_espacio="Casa",
        tipo_intervencion="Remodelación",
        area_aprox="80 metros",
        situacion_actual="Muy deteriorada",
        fecha_deseada="Junio",
        presupuesto="50 millones",
        alcance="Cocina y baños",
    )

    history: list[dict[str, str]] = []
    leads: dict[str, dict[str, Any]] = {}
    save_count = 0
    mark_closed_count = 0
    llm_i = 0
    ext_i = 0

    def get_conversation_history(c: str) -> list[dict[str, str]]:
        assert str(c).strip() == cid
        return [dict(x) for x in history]

    def get_lead(c: str) -> dict[str, Any] | None:
        row = leads.get(str(c).strip())
        if not row:
            return None
        out: dict[str, Any] = {"chat_id": str(c).strip()}
        for k in LEAD_DATA_KEYS:
            out[k] = row.get(k)
        out["estado"] = row.get("estado", "")
        return out

    def save_conversation_turn(
        c: str,
        role: str,
        content: str,
        timestamp: int,
        estado: str,
    ) -> None:
        nonlocal save_count
        save_count += 1
        history.append({"role": role, "content": content})

    def upsert_lead(
        c: str,
        lead_record: dict[str, Any],
        estado: str | None = None,
    ) -> bool:
        c = str(c).strip()
        if c not in leads:
            leads[c] = {k: None for k in LEAD_DATA_KEYS}
            leads[c]["estado"] = estado or "en_curso"
        row = leads[c]
        for k in LEAD_DATA_KEYS:
            inc = lead_record.get(k)
            if inc is None or str(inc).strip() == "":
                continue
            cur = row.get(k)
            if cur is None or str(cur).strip() == "":
                row[k] = str(inc).strip()
        if estado is not None:
            row["estado"] = estado
        return True

    def mark_conversation_closed(c: str) -> None:
        nonlocal mark_closed_count
        mark_closed_count += 1

    def llm_create(*_a: Any, **_kw: Any) -> MagicMock:
        nonlocal llm_i
        llm_i += 1
        if llm_i < len(user_lines):
            return _conv_completion("Entendido, sigamos.")
        return _conv_completion(f"Agenda aquí: {config.CALENDLY_URL}")

    def extract_lead_data(_hist: list[dict[str, Any]], _cid: str | int) -> LeadRecord | None:
        nonlocal ext_i
        ext_i += 1
        if ext_i <= len(progressive):
            return progressive[ext_i - 1]
        return final_record

    with (
        patch("bot.conversation.storage.get_conversation_history", side_effect=get_conversation_history),
        patch("bot.conversation.storage.get_lead", side_effect=get_lead),
        patch("bot.conversation.storage.save_conversation_turn", side_effect=save_conversation_turn),
        patch("bot.conversation.storage.upsert_lead", side_effect=upsert_lead),
        patch("bot.conversation.storage.mark_conversation_closed", side_effect=mark_conversation_closed),
        patch("bot.conversation.config.llm.chat.completions.create", side_effect=llm_create),
        patch("bot.conversation.extraction.extract_lead_data", side_effect=extract_lead_data),
    ):
        ts = 1
        for line in user_lines:
            process_message(cid, 1, line, ts, False)
            ts += 1

    assert save_count == len(user_lines) * 2
    assert mark_closed_count == 1
    row = leads[cid]
    assert row["estado"] == "calendly_enviado"
    for k in LEAD_DATA_KEYS:
        assert row.get(k) not in (None, ""), k
    assert row["nombre"] == "Luis"
    assert row["alcance"] == "Cocina y baños"

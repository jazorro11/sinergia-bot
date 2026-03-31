"""Unit tests for bot.conversation and webhook DoD cases."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import config
from bot.conversation import _remove_dangling_calendly_teasers, process_message
from bot.extraction import LeadRecord
from bot.storage import LEADS_HEADERS, upsert_lead


def _conv_completion(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.is_silence_hours", return_value=True)
def test_silence_hours_no_llm_no_storage_reads(
    _silence: MagicMock,
    mock_llm: MagicMock,
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
) -> None:
    out = process_message(1, 1, "hola", 12345, False)
    assert out == config.MSG_SILENCE_ABSENCE
    mock_llm.assert_not_called()
    mock_get_lead.assert_not_called()
    mock_get_history.assert_not_called()


@patch("bot.conversation.storage.mark_conversation_closed")
@patch("bot.conversation.storage.upsert_lead")
@patch("bot.conversation.extraction.extract_lead_data")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_user_message_limit_triggers_final_extraction_and_closure(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_extract: MagicMock,
    mock_upsert: MagicMock,
    mock_mark_closed: MagicMock,
) -> None:
    mock_get_lead.return_value = None
    mock_get_history.return_value = [
        {"role": "user", "content": f"m{i}"} for i in range(30)
    ]
    mock_extract.return_value = LeadRecord(nombre="X")
    out = process_message(1, 1, "one more", 12345, False)
    mock_extract.assert_called_once()
    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.kwargs["estado"] == "limite_alcanzado"
    mock_mark_closed.assert_called_once()
    assert config.CALENDLY_URL in out


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.storage.mark_conversation_closed")
@patch("bot.conversation.storage.upsert_lead")
@patch("bot.conversation.extraction.extract_lead_data")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_calendly_in_assistant_response_closes_once(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    mock_extract: MagicMock,
    mock_upsert: MagicMock,
    mock_mark_closed: MagicMock,
    _save: MagicMock,
) -> None:
    mock_get_lead.return_value = None
    mock_get_history.return_value = []
    mock_llm.return_value = _conv_completion(
        f"Listo, agenda aquí: {config.CALENDLY_URL}"
    )
    mock_extract.return_value = LeadRecord(
        nombre="N", ciudad="Bogotá", area_aprox="80"
    )
    mock_upsert.return_value = True
    out = process_message(42, 7, "quiero agendar", 999, False)
    assert config.CALENDLY_URL in out
    mock_extract.assert_called_once()
    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.kwargs["estado"] == "calendly_enviado"
    mock_mark_closed.assert_called_once()


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.storage.mark_conversation_closed")
@patch("bot.conversation.storage.upsert_lead")
@patch("bot.conversation.extraction.extract_lead_data")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_calendly_blocked_when_minimum_fields_missing(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    mock_extract: MagicMock,
    mock_upsert: MagicMock,
    mock_mark_closed: MagicMock,
    _save: MagicMock,
) -> None:
    mock_get_lead.return_value = None
    mock_get_history.return_value = []
    mock_llm.return_value = _conv_completion(
        f"Listo: {config.CALENDLY_URL}"
    )
    mock_extract.return_value = LeadRecord(nombre="SoloNombre")
    out = process_message(1, 1, "agendar ya", 1, False)
    assert config.CALENDLY_URL not in out
    mock_mark_closed.assert_not_called()
    assert not any(
        c.kwargs.get("estado") == "calendly_enviado"
        for c in mock_upsert.call_args_list
    )


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.storage.mark_conversation_closed")
@patch("bot.conversation.storage.upsert_lead")
@patch("bot.conversation.extraction.extract_lead_data")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_calendly_blocked_strips_markdown_link_without_empty_brackets(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    mock_extract: MagicMock,
    mock_upsert: MagicMock,
    mock_mark_closed: MagicMock,
    _save: MagicMock,
) -> None:
    """Si el LLM usa [url](url) y faltan mínimos, no debe quedar []() al quitar Calendly."""
    u = config.CALENDLY_URL
    mock_get_lead.return_value = None
    mock_get_history.return_value = []
    mock_llm.return_value = _conv_completion(
        f"Te dejo el enlace: [{u}]({u})"
    )
    mock_extract.return_value = LeadRecord(nombre="SoloNombre")
    out = process_message(1, 1, "agendar ya", 1, False)
    assert config.CALENDLY_URL not in out
    assert "[]()" not in out
    assert "[] (" not in out
    mock_mark_closed.assert_not_called()
    assert not any(
        c.kwargs.get("estado") == "calendly_enviado"
        for c in mock_upsert.call_args_list
    )


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.storage.mark_conversation_closed")
@patch("bot.conversation.storage.upsert_lead")
@patch("bot.conversation.extraction.extract_lead_data")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_calendly_blocked_removes_agenda_aca_without_url(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    mock_extract: MagicMock,
    mock_upsert: MagicMock,
    mock_mark_closed: MagicMock,
    _save: MagicMock,
) -> None:
    """No debe quedar 'Cuando quieras agenda acá:' si el enlace está bloqueado por mínimos."""
    u = config.CALENDLY_URL
    mock_get_lead.return_value = None
    mock_get_history.return_value = []
    mock_llm.return_value = _conv_completion(
        f"Sí, ofrecemos diseño personalizado con la línea plus. "
        f"¿Te gustaría agendar una videollamada? Cuando quieras agenda acá:\n\n[{u}]({u})"
    )
    mock_extract.return_value = LeadRecord(nombre="SoloNombre")
    out = process_message(1, 1, "hola", 1, False)
    assert config.CALENDLY_URL not in out
    assert "agenda acá" not in out.lower()
    assert "cuando quieras" not in out.lower()
    assert "por favor" in out.lower()
    mock_mark_closed.assert_not_called()


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
@patch("bot.conversation.config.llm.chat.completions.create")
def test_conversational_llm_respects_history_window(
    mock_llm: MagicMock,
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    _save: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.conversation.config.CONVERSATION_HISTORY_MAX_MESSAGES", 4)
    mock_get_lead.return_value = None
    long_hist = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": str(i)}
        for i in range(20)
    ]
    mock_get_history.return_value = long_hist
    mock_llm.return_value = _conv_completion("ok")
    process_message(1, 1, "nuevo", 1, False)
    msgs = mock_llm.call_args.kwargs["messages"]
    assert msgs[0]["role"] == "system"
    assert len(msgs) == 6
    assert [m["content"] for m in msgs[1:-1]] == ["16", "17", "18", "19"]
    assert msgs[-1] == {"role": "user", "content": "nuevo"}


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_post_calendly_farewell_sends_trimmed_history(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    _save: MagicMock,
) -> None:
    filler = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "viejo"}] * 8
    mock_get_lead.return_value = {"estado": "calendly_enviado", "chat_id": "1"}
    mock_get_history.return_value = [
        *filler,
        {"role": "user", "content": "agendar"},
        {"role": "assistant", "content": f"Link {config.CALENDLY_URL}"},
    ]
    mock_llm.return_value = _conv_completion("Hasta luego")
    process_message(1, 1, "gracias", 100, False)
    msgs = mock_llm.call_args.kwargs["messages"]
    assert len(msgs) == 3
    assert config.CALENDLY_URL in msgs[1]["content"]
    assert msgs[2] == {"role": "user", "content": "gracias"}


def test_remove_dangling_calendly_teasers_strips_known_tails() -> None:
    assert "agenda" not in _remove_dangling_calendly_teasers(
        "Diseño plus te puede servir. Cuando quieras agenda acá:"
    ).lower()
    assert not _remove_dangling_calendly_teasers("Solo: Cuando quieras agenda acá:").endswith(
        ":"
    )


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.storage.upsert_lead")
@patch("bot.conversation.extraction.extract_lead_data")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_extraction_frequency_every_second_message(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    mock_extract: MagicMock,
    mock_upsert: MagicMock,
    _save: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.conversation.config.EXTRACTION_FREQUENCY", 2)
    mock_get_lead.return_value = None
    mock_llm.return_value = _conv_completion("sigamos")
    mock_extract.return_value = LeadRecord(ciudad="Y")
    histories = [
        [],
        [{"role": "user", "content": "a"}],
        [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ],
    ]
    mock_get_history.side_effect = histories.copy()
    process_message(1, 1, "first", 1, False)
    process_message(1, 1, "second", 2, False)
    process_message(1, 1, "third", 3, False)
    assert mock_extract.call_count == 1


@patch("bot.storage._worksheet")
def test_upsert_lead_does_not_overwrite_existing_with_none(
    mock_worksheet: MagicMock,
) -> None:
    headers = list(LEADS_HEADERS)
    row = [""] * len(headers)
    col = {h: i for i, h in enumerate(headers)}
    row[col["chat_id"]] = "7"
    row[col["nombre"]] = "Carlos"
    row[col["estado"]] = "en_curso"
    row[col["created_at"]] = "2020-01-01T00:00:00+00:00"
    row[col["updated_at"]] = "2020-01-01T00:00:00+00:00"
    ws = MagicMock()
    ws.get_all_values.return_value = [headers, row]
    mock_worksheet.return_value = ws
    assert upsert_lead(
        "7",
        {"nombre": None, "ciudad": "Bogotá"},
        estado=None,
    )
    ws.batch_update.assert_called_once()
    batch = ws.batch_update.call_args[0][0]
    assert any(u.get("values") == [["Bogotá"]] for u in batch)
    assert not any(
        u.get("values") == [[""]] or u.get("values") == [[None]] for u in batch
    )
    # nombre "Carlos" must not be sent as an update value
    flat_vals = [v for u in batch for row_ in u.get("values", []) for v in row_]
    assert "Carlos" not in flat_vals


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
@patch("bot.conversation.config.llm.chat.completions.create")
def test_llm_failure_returns_fallback_and_logs_error(
    mock_llm: MagicMock,
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    _save: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_get_lead.return_value = None
    mock_get_history.return_value = []
    mock_llm.side_effect = RuntimeError("timeout")
    caplog.set_level("ERROR", logger="bot.conversation")
    out = process_message(1, 1, "hola", 1, False)
    assert out == config.MSG_FALLBACK_LLM
    assert any(r.levelname == "ERROR" for r in caplog.records)


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_post_calendly_farewell_first_user_message_uses_llm(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    _save: MagicMock,
) -> None:
    mock_get_lead.return_value = {"estado": "calendly_enviado", "chat_id": "1"}
    mock_get_history.return_value = [
        {"role": "user", "content": "quiero agendar"},
        {"role": "assistant", "content": f"Aquí: {config.CALENDLY_URL}"},
    ]
    mock_llm.return_value = _conv_completion("Un gusto, nos vemos en la llamada")
    out = process_message(1, 1, "gracias!", 100, False)
    mock_llm.assert_called_once()
    assert out == "Un gusto, nos vemos en la llamada"
    fixed = config.MSG_CLOSED_CALENDLY_OR_LIMIT_TEMPLATE.format(
        calendly_url=config.CALENDLY_URL
    )
    assert out != fixed


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_post_calendly_farewell_third_user_message_returns_fixed_template(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    _save: MagicMock,
) -> None:
    mock_get_lead.return_value = {"estado": "calendly_enviado", "chat_id": "1"}
    mock_get_history.return_value = [
        {"role": "assistant", "content": f"Link {config.CALENDLY_URL}"},
        {"role": "user", "content": "gracias"},
        {"role": "assistant", "content": "de nada"},
        {"role": "user", "content": "chao"},
    ]
    out = process_message(1, 1, "ok", 101, False)
    mock_llm.assert_not_called()
    assert out == config.MSG_CLOSED_CALENDLY_OR_LIMIT_TEMPLATE.format(
        calendly_url=config.CALENDLY_URL
    )


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_post_calendly_farewell_inferred_close_without_lead_row(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    _save: MagicMock,
) -> None:
    mock_get_lead.return_value = None
    mock_get_history.return_value = [
        {"role": "assistant", "content": f"Agenda acá {config.CALENDLY_URL}"},
    ]
    mock_llm.return_value = _conv_completion("Perfecto, hablamos pronto")
    out = process_message(9, 9, "listo gracias", 102, False)
    mock_llm.assert_called_once()
    assert out == "Perfecto, hablamos pronto"


@patch("bot.conversation.storage.save_conversation_turn")
@patch("bot.conversation.config.llm.chat.completions.create")
@patch("bot.conversation.storage.get_conversation_history")
@patch("bot.conversation.storage.get_lead")
def test_post_calendly_farewell_limite_alcanzado_first_message_uses_llm(
    mock_get_lead: MagicMock,
    mock_get_history: MagicMock,
    mock_llm: MagicMock,
    _save: MagicMock,
) -> None:
    mock_get_lead.return_value = {"estado": "limite_alcanzado", "chat_id": "2"}
    mock_get_history.return_value = [
        {"role": "assistant", "content": f"Enlace {config.CALENDLY_URL}"},
    ]
    mock_llm.return_value = _conv_completion("Quedamos atentos")
    out = process_message(2, 2, "gracias", 103, False)
    mock_llm.assert_called_once()
    assert out == "Quedamos atentos"


def test_webhook_returns_200_and_schedules_background_task() -> None:
    from fastapi.testclient import TestClient

    from bot import webhook as wh

    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": 1001, "type": "private"},
            "from": {"id": 2002, "is_bot": False, "first_name": "T"},
            "text": "hola",
        },
    }
    mock_bot = MagicMock()
    mock_bot.initialize = AsyncMock()
    mock_bot.shutdown = AsyncMock()
    mock_bot.send_message = AsyncMock()
    def _fake_create_task(coro: Coroutine[Any, Any, None]) -> MagicMock:
        coro.close()
        t = MagicMock()
        t.add_done_callback = MagicMock()
        return t

    with (
        patch("bot.webhook.telegram_bot", mock_bot),
        patch("bot.webhook.asyncio.create_task", side_effect=_fake_create_task) as mock_ct,
    ):
        with TestClient(wh.app) as client:
            r = client.post("/webhook", json=payload)
    assert r.status_code == 200
    mock_ct.assert_called()

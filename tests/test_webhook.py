"""Tests for debounce, typing hooks, and POST_LLM_DELAY (webhook layer).

Matriz manual en Telegram (registrar en el piloto):
| # | MESSAGE_DEBOUNCE_SECONDS | TELEGRAM_TYPING_ENABLED | POST_LLM_DELAY_MS | Comprobar |
|---|--------------------------|-------------------------|-------------------|-----------|
| 1 | 0 | false | 1000 | Baseline |
| 2 | 0 | true | 1000 | «Escribiendo» durante LLM + delay |
| 3 | 10 | true | 1500 | Dos mensajes rápidos → una respuesta; un turno user en Sheets |
| 4 | 10 | true | 0 | Ventana de espera + typing, sin sleep extra |
| 5 | 10 | false | 1000 | Acumulación sin indicador |
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bot import webhook


@pytest.fixture(autouse=True)
def _clear_debounce_state() -> None:
    webhook._debounce_entries.clear()
    webhook._debounce_locks.clear()
    yield
    webhook._debounce_entries.clear()
    webhook._debounce_locks.clear()


@pytest.mark.asyncio
async def test_debounce_merges_two_messages_one_process_call() -> None:
    calls: list[str] = []

    async def fake_process(
        _chat_id: int | str,
        _user_id: int | str,
        text: str,
        _timestamp: int,
        _is_edited: bool,
    ) -> None:
        calls.append(text)

    with (
        patch.object(webhook.config, "MESSAGE_DEBOUNCE_SECONDS", 0.08),
        patch.object(webhook.config, "MESSAGE_DEBOUNCE_JOIN", "\n\n"),
        patch.object(webhook.config, "TELEGRAM_TYPING_ENABLED", False),
        patch.object(webhook.config, "POST_LLM_DELAY_MS", 0),
        patch.object(webhook, "_process_text_and_reply", side_effect=fake_process),
    ):
        await webhook._debounce_enqueue_text(42, 100, "hola", 1)
        await asyncio.sleep(0.02)
        await webhook._debounce_enqueue_text(42, 100, "mundo", 2)
        await asyncio.sleep(0.2)

    assert len(calls) == 1
    assert calls[0] == "hola\n\nmundo"


@pytest.mark.asyncio
async def test_debounce_two_messages_separate_when_window_expires() -> None:
    calls: list[str] = []

    async def fake_process(
        _chat_id: int | str,
        _user_id: int | str,
        text: str,
        _timestamp: int,
        _is_edited: bool,
    ) -> None:
        calls.append(text)

    with (
        patch.object(webhook.config, "MESSAGE_DEBOUNCE_SECONDS", 0.06),
        patch.object(webhook.config, "MESSAGE_DEBOUNCE_JOIN", " "),
        patch.object(webhook.config, "TELEGRAM_TYPING_ENABLED", False),
        patch.object(webhook.config, "POST_LLM_DELAY_MS", 0),
        patch.object(webhook, "_process_text_and_reply", side_effect=fake_process),
    ):
        await webhook._debounce_enqueue_text(7, 1, "a", 1)
        await asyncio.sleep(0.15)
        await webhook._debounce_enqueue_text(7, 1, "b", 2)
        await asyncio.sleep(0.15)

    assert calls == ["a", "b"]


@pytest.mark.asyncio
async def test_process_text_and_reply_sends_typing_when_enabled() -> None:
    sent_actions: list[str] = []

    async def fake_typing(_chat_id: int | str, _stop: asyncio.Event) -> None:
        sent_actions.append("typing")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with (
        patch.object(webhook.config, "TELEGRAM_TYPING_ENABLED", True),
        patch.object(webhook.config, "POST_LLM_DELAY_MS", 0),
        patch.object(webhook, "_typing_keepalive", side_effect=fake_typing),
        patch.object(
            webhook.conversation,
            "process_message",
            return_value="ok",
        ),
        patch("bot.webhook.telegram_bot", mock_bot),
    ):
        await webhook._process_text_and_reply(1, 100, "x", 999, False)

    assert sent_actions == ["typing"]
    mock_bot.send_message.assert_awaited_once()


def test_webhook_returns_200_immediately() -> None:
    body = {
        "message": {
            "chat": {"id": 1},
            "from": {"id": 2},
            "date": 1700000000,
            "text": "hola",
        }
    }
    mock_bot = MagicMock()
    mock_bot.initialize = AsyncMock()
    mock_bot.shutdown = AsyncMock()
    def _discard_scheduled(coro):  # evita RuntimeWarning: coroutine was never awaited
        coro.close()

    with (
        patch.object(webhook, "_schedule", _discard_scheduled),
        patch.object(webhook.config, "MESSAGE_DEBOUNCE_SECONDS", 0),
        patch("bot.webhook.telegram_bot", mock_bot),
        patch("bot.webhook.storage.validate_sheets_schema"),
    ):
        client = TestClient(webhook.app)
        r = client.post("/webhook", json=body)
    assert r.status_code == 200


def test_webhook_json_malformed_still_200() -> None:
    mock_bot = MagicMock()
    mock_bot.initialize = AsyncMock()
    mock_bot.shutdown = AsyncMock()
    with (
        patch("bot.webhook.telegram_bot", mock_bot),
        patch("bot.webhook.storage.validate_sheets_schema"),
    ):
        client = TestClient(webhook.app)
        r = client.post(
            "/webhook", content=b"not-json", headers={"Content-Type": "application/json"}
        )
    assert r.status_code == 200

"""FastAPI webhook: POST /webhook only. No business logic."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import Coroutine
from typing import Any

from fastapi import FastAPI, Request, Response
from telegram import Bot
from telegram.error import TelegramError

from bot import config
from bot import conversation
from bot.logger import get_logger

logger = get_logger(__name__)

telegram_bot = Bot(config.TELEGRAM_BOT_TOKEN)

_CONTENT_KEYS: tuple[str, ...] = (
    "photo",
    "video",
    "voice",
    "video_note",
    "document",
    "sticker",
    "animation",
    "audio",
    "contact",
    "location",
    "poll",
    "dice",
    "venue",
)


def _infer_content_type(msg: dict[str, Any]) -> str:
    for key in _CONTENT_KEYS:
        if key in msg:
            return key
    return "unknown"


def _extract_message_payload(update: dict[str, Any]) -> tuple[dict[str, Any], bool] | None:
    if "message" in update:
        raw = update["message"]
        if isinstance(raw, dict):
            return raw, False
        return None
    if "edited_message" in update:
        raw = update["edited_message"]
        if isinstance(raw, dict):
            return raw, True
        return None
    return None


def _task_done_callback(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Tarea background no capturada: error=%s", repr(exc))


async def _send_unsupported_reply(chat_id: int | str) -> None:
    try:
        await telegram_bot.send_message(chat_id=chat_id, text=config.MSG_UNSUPPORTED_CONTENT)
    except TelegramError as e:
        logger.error("Error enviando a Telegram: chat_id=%s, error=%s", chat_id, repr(e))
    except Exception as e:
        logger.error("Error enviando a Telegram: chat_id=%s, error=%s", chat_id, repr(e))


async def _process_text_and_reply(
    chat_id: int | str,
    user_id: int | str,
    text: str,
    timestamp: int,
    is_edited: bool,
) -> None:
    try:
        reply = await asyncio.to_thread(
            conversation.process_message,
            chat_id,
            user_id,
            text,
            timestamp,
            is_edited,
        )
    except Exception:
        logger.exception("Error en process_message: chat_id=%s", chat_id)
        return

    try:
        await asyncio.sleep(config.RESPONSE_DELAY_MS / 1000.0)
        await telegram_bot.send_message(chat_id=chat_id, text=reply)
    except TelegramError as e:
        logger.error("Error enviando a Telegram: chat_id=%s, error=%s", chat_id, repr(e))
    except Exception as e:
        logger.error("Error enviando a Telegram: chat_id=%s, error=%s", chat_id, repr(e))


def _schedule(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    task.add_done_callback(_task_done_callback)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await telegram_bot.initialize()
    try:
        yield
    finally:
        await telegram_bot.shutdown()


app = FastAPI(lifespan=_lifespan)


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    try:
        body: Any = await request.json()
    except Exception:
        logger.debug("Body JSON inválido o vacío en /webhook")
        return Response(status_code=200)

    if not isinstance(body, dict):
        return Response(status_code=200)

    extracted = _extract_message_payload(body)
    if extracted is None:
        logger.debug("Update sin message ni edited_message: keys=%s", list(body.keys()))
        return Response(status_code=200)

    msg, is_edited = extracted
    if not isinstance(msg, dict):
        return Response(status_code=200)

    chat = msg.get("chat")
    if not isinstance(chat, dict):
        logger.debug("Mensaje sin chat válido")
        return Response(status_code=200)

    chat_id = chat.get("id")
    if chat_id is None:
        logger.debug("Mensaje sin chat.id")
        return Response(status_code=200)

    from_user = msg.get("from")
    if not isinstance(from_user, dict) or from_user.get("id") is None:
        logger.info("Webhook sin from o user id: chat_id=%s", chat_id)
        return Response(status_code=200)

    user_id = from_user["id"]
    timestamp = msg.get("date")
    if not isinstance(timestamp, int):
        logger.info("Webhook sin date válido: chat_id=%s", chat_id)
        return Response(status_code=200)

    text = msg.get("text")
    if text is not None and not isinstance(text, str):
        text = str(text)

    if text is None or not text.strip():
        if is_edited:
            logger.info("Mensaje editado: chat_id=%s", chat_id)
        tipo = _infer_content_type(msg)
        logger.info("Contenido no soportado: chat_id=%s, tipo=%s", chat_id, tipo)
        _schedule(_send_unsupported_reply(chat_id))
        return Response(status_code=200)

    if is_edited:
        logger.info("Mensaje editado: chat_id=%s", chat_id)
    else:
        logger.info("Webhook recibido: chat_id=%s, tipo=text", chat_id)

    _schedule(
        _process_text_and_reply(
            chat_id,
            user_id,
            text.strip(),
            timestamp,
            is_edited,
        )
    )
    return Response(status_code=200)

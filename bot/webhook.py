"""FastAPI webhook: POST /webhook only.

Edge cases (typing + debounce):
- edited_message: no se acumula; se procesa en cuanto llega el update (misma ruta que debounce off).
- Debounce en memoria por chat_id: requiere una sola instancia del proceso; varias réplicas necesitan store compartido.
- Fusionar varias burbujas en un turno reduce el conteo de mensajes usuario en Sheets frente a procesarlas
  por separado; afecta EXTRACTION_FREQUENCY y el acercamiento a USER_MESSAGE_LIMIT (ver conversation.py).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request, Response
from telegram import Bot
from telegram.constants import ChatAction
from telegram.error import TelegramError

from bot import config
from bot import conversation
from bot import storage
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


@dataclass
class _DebounceEntry:
    generation: int = 0
    parts: list[str] = field(default_factory=list)
    user_id: int | str = 0
    last_timestamp: int = 0
    flush_task: asyncio.Task[None] | None = None


_debounce_entries: dict[int | str, _DebounceEntry] = {}
_debounce_locks: dict[int | str, asyncio.Lock] = {}


def _debounce_lock(chat_id: int | str) -> asyncio.Lock:
    return _debounce_locks.setdefault(chat_id, asyncio.Lock())


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


async def _typing_keepalive(chat_id: int | str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await telegram_bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING,
            )
        except TelegramError as e:
            logger.debug("[typing] send_chat_action chat_id=%s err=%s", chat_id, repr(e))
        except Exception as e:
            logger.debug("[typing] send_chat_action chat_id=%s err=%s", chat_id, repr(e))
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=config.TYPING_RENEW_INTERVAL_SECONDS,
            )
            return
        except asyncio.TimeoutError:
            continue


async def _process_text_and_reply(
    chat_id: int | str,
    user_id: int | str,
    text: str,
    timestamp: int,
    is_edited: bool,
) -> None:
    stop_typing = asyncio.Event()
    typing_task: asyncio.Task[None] | None = None
    if config.TELEGRAM_TYPING_ENABLED:
        typing_task = asyncio.create_task(_typing_keepalive(chat_id, stop_typing))

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
        stop_typing.set()
        if typing_task:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass
        return

    try:
        await asyncio.sleep(config.POST_LLM_DELAY_MS / 1000.0)
        await telegram_bot.send_message(chat_id=chat_id, text=reply)
    except TelegramError as e:
        logger.error("Error enviando a Telegram: chat_id=%s, error=%s", chat_id, repr(e))
    except Exception as e:
        logger.error("Error enviando a Telegram: chat_id=%s, error=%s", chat_id, repr(e))
    finally:
        stop_typing.set()
        if typing_task:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass


async def _debounce_wait_and_flush(chat_id: int | str, expected_gen: int) -> None:
    stop_typing = asyncio.Event()
    typing_task: asyncio.Task[None] | None = None
    if config.TELEGRAM_TYPING_ENABLED:
        typing_task = asyncio.create_task(_typing_keepalive(chat_id, stop_typing))
    try:
        await asyncio.sleep(float(config.MESSAGE_DEBOUNCE_SECONDS))
    except asyncio.CancelledError:
        logger.info(
            "[debounce] reset chat_id=%s gen=%s (cancelled, new message or shutdown)",
            chat_id,
            expected_gen,
        )
        raise
    finally:
        stop_typing.set()
        if typing_task:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

    lock = _debounce_lock(chat_id)
    async with lock:
        entry = _debounce_entries.get(chat_id)
        if entry is None or entry.generation != expected_gen:
            logger.debug("[debounce] skip_stale_flush chat_id=%s", chat_id)
            return
        merged = config.MESSAGE_DEBOUNCE_JOIN.join(entry.parts)
        n_parts = len(entry.parts)
        last_ts = entry.last_timestamp
        uid = entry.user_id
        del _debounce_entries[chat_id]

    logger.info(
        "[debounce] flush chat_id=%s merged_parts=%s merged_chars=%s",
        chat_id,
        n_parts,
        len(merged),
    )
    await _process_text_and_reply(chat_id, uid, merged, last_ts, False)


async def _debounce_enqueue_text(
    chat_id: int | str,
    user_id: int | str,
    text: str,
    timestamp: int,
) -> None:
    lock = _debounce_lock(chat_id)
    async with lock:
        entry = _debounce_entries.setdefault(chat_id, _DebounceEntry())
        had_pending = entry.flush_task is not None and not entry.flush_task.done()
        if had_pending:
            entry.flush_task.cancel()
        entry.generation += 1
        gen = entry.generation
        entry.parts.append(text)
        entry.user_id = user_id
        entry.last_timestamp = timestamp
        if had_pending:
            try:
                assert entry.flush_task is not None
                await entry.flush_task
            except asyncio.CancelledError:
                pass
        logger.info(
            "[debounce] scheduled chat_id=%s parts=%s gen=%s",
            chat_id,
            len(entry.parts),
            gen,
        )
        entry.flush_task = asyncio.create_task(_debounce_wait_and_flush(chat_id, gen))


async def _send_unsupported_reply(chat_id: int | str) -> None:
    try:
        await telegram_bot.send_message(chat_id=chat_id, text=config.MSG_UNSUPPORTED_CONTENT)
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
    storage.validate_sheets_schema()
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

    stripped = text.strip()
    if config.MESSAGE_DEBOUNCE_SECONDS > 0 and not is_edited:
        _schedule(_debounce_enqueue_text(chat_id, user_id, stripped, timestamp))
    else:
        if is_edited and config.MESSAGE_DEBOUNCE_SECONDS > 0:
            logger.debug("[debounce] bypass edited_message chat_id=%s", chat_id)
        _schedule(
            _process_text_and_reply(
                chat_id,
                user_id,
                stripped,
                timestamp,
                is_edited,
            )
        )
    return Response(status_code=200)

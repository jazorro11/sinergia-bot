"""Google Sheets persistence for conversation history and leads. Sole module that talks to Sheets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, TypedDict

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption

from bot import config
from bot.logger import get_logger

logger = get_logger(__name__)

_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

# Hoja conversaciones: timestamp = Unix segundos (Telegram) como string para ordenar.

LEAD_DATA_KEYS = (
    "nombre",
    "ciudad",
    "tipo_espacio",
    "tipo_intervencion",
    "area_aprox",
    "situacion_actual",
    "fecha_deseada",
    "presupuesto",
    "alcance",
)

# Orden de columnas en hoja leads (debe coincidir con fila 1 del Sheet).
LEADS_HEADERS = (
    "chat_id",
    *LEAD_DATA_KEYS,
    "estado",
    "created_at",
    "updated_at",
)

# Hoja conversaciones: columnas mínimas para append y cierre.
CONVERSACIONES_REQUIRED_HEADERS = (
    "chat_id",
    "role",
    "content",
    "timestamp",
    "estado",
)


class LeadFields(TypedDict, total=False):
    """Nine optional lead fields from extraction; compatible with LeadRecord.model_dump()."""

    nombre: str | None
    ciudad: str | None
    tipo_espacio: str | None
    tipo_intervencion: str | None
    area_aprox: str | None
    situacion_actual: str | None
    fecha_deseada: str | None
    presupuesto: str | None
    alcance: str | None


_gc: gspread.Client | None = None


def _norm_chat_id(chat_id: str | int) -> str:
    return str(chat_id).strip()


def _credentials() -> Credentials:
    return Credentials.from_service_account_info(
        config.GOOGLE_SERVICE_ACCOUNT_CREDENTIALS,
        scopes=_SCOPES,
    )


def _client() -> gspread.Client:
    global _gc
    if _gc is None:
        _gc = gspread.authorize(_credentials())
    return _gc


def _spreadsheet() -> gspread.Spreadsheet:
    return _client().open_by_key(config.GOOGLE_SHEET_ID)


def _worksheet(name: str) -> gspread.Worksheet:
    return _spreadsheet().worksheet(name)


def _header_index_map(headers: list[str]) -> dict[str, int]:
    return {h.strip(): i for i, h in enumerate(headers)}


def _col_a1(zero_based: int) -> str:
    col = zero_based + 1
    letters = ""
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _is_blank_cell(value: str | None) -> bool:
    return value is None or str(value).strip() == ""


def _incoming_value(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _sort_key_timestamp(raw: str) -> tuple[int, str]:
    s = str(raw).strip()
    try:
        return (int(s), s)
    except ValueError:
        try:
            f = float(s)
            return (int(f), s)
        except ValueError:
            return (0, s)


def _count_lead_fields_filled(row: Mapping[str, Any]) -> int:
    return sum(1 for k in LEAD_DATA_KEYS if not _is_blank_cell(row.get(k)))


def _lead_field_values(
    record: LeadFields | Mapping[str, str | None],
) -> dict[str, str | None]:
    return {k: record.get(k) for k in LEAD_DATA_KEYS}


def _row_cell(row: list[str], col_map: dict[str, int], name: str) -> str:
    j = col_map[name]
    return row[j].strip() if j < len(row) else ""


def get_conversation_history(chat_id: str) -> list[dict[str, str]]:
    cid = _norm_chat_id(chat_id)
    try:
        ws = _worksheet("conversaciones")
        rows = ws.get_all_values()
        if not rows:
            logger.debug("Historial leído: chat_id=%s, turnos=0", cid)
            return []
        headers = [h.strip() for h in rows[0]]
        col_map = _header_index_map(headers)
        required = ("chat_id", "role", "content", "timestamp")
        for r in required:
            if r not in col_map:
                raise ValueError(f"conversaciones: falta columna {r!r} en encabezados")

        matching: list[tuple[tuple[int, str], dict[str, str]]] = []
        for row in rows[1:]:
            if len(row) <= col_map["chat_id"]:
                continue
            if _norm_chat_id(row[col_map["chat_id"]]) != cid:
                continue

            role = _row_cell(row, col_map, "role")
            content = _row_cell(row, col_map, "content")
            ts = _row_cell(row, col_map, "timestamp")
            if role not in ("user", "assistant"):
                continue
            matching.append(
                (_sort_key_timestamp(ts), {"role": role, "content": content})
            )

        matching.sort(key=lambda x: x[0])
        out = [m[1] for m in matching]
        logger.debug("Historial leído: chat_id=%s, turnos=%s", cid, len(out))
        return out
    except Exception:
        logger.exception("Error leyendo historial: chat_id=%s", cid)
        raise


def save_conversation_turn(
    chat_id: str,
    role: str,
    content: str,
    timestamp: int,
    estado: str,
) -> None:
    cid = _norm_chat_id(chat_id)
    try:
        ws = _worksheet("conversaciones")
        headers = [h.strip() for h in ws.row_values(1)]
        col_map = _header_index_map(headers)
        row_out = [""] * len(headers)
        for name, val in (
            ("chat_id", cid),
            ("role", role),
            ("content", content),
            ("timestamp", str(int(timestamp))),
            ("estado", estado),
        ):
            if name in col_map:
                row_out[col_map[name]] = val
        ws.append_row(row_out, value_input_option=ValueInputOption.user_entered)
    except Exception:
        logger.exception(
            "Error guardando turno conversación: chat_id=%s role=%s",
            cid,
            role,
        )


def validate_sheets_schema() -> None:
    """Registra ERROR si faltan encabezados; no lanza (arranque del servidor)."""
    for sheet_name, required in (
        ("leads", LEADS_HEADERS),
        ("conversaciones", CONVERSACIONES_REQUIRED_HEADERS),
    ):
        try:
            ws = _worksheet(sheet_name)
            rows = ws.get_all_values()
            if not rows:
                logger.error(
                    "Sheets: hoja %r vacía. Fila 1 debe incluir: %s",
                    sheet_name,
                    list(required),
                )
                continue
            headers = [h.strip() for h in rows[0]]
            col_map = _header_index_map(headers)
            for h in required:
                if h not in col_map:
                    logger.error(
                        "Sheets: hoja %r falta columna %r. Encabezados actuales: %s",
                        sheet_name,
                        h,
                        headers,
                    )
        except Exception:
            logger.exception(
                "Sheets: no se pudo validar el esquema de la hoja %r", sheet_name
            )


def get_lead(chat_id: str) -> dict[str, Any] | None:
    cid = _norm_chat_id(chat_id)
    try:
        ws = _worksheet("leads")
        rows = ws.get_all_values()
        if not rows:
            return None
        headers = [h.strip() for h in rows[0]]
        col_map = _header_index_map(headers)
        if "chat_id" not in col_map:
            raise ValueError("leads: falta columna 'chat_id'")

        for row in rows[1:]:
            if len(row) <= col_map["chat_id"]:
                continue
            if _norm_chat_id(row[col_map["chat_id"]]) != cid:
                continue
            record: dict[str, Any] = {}
            for h, idx in col_map.items():
                record[h] = row[idx].strip() if idx < len(row) else ""
            return record
        return None
    except Exception:
        logger.exception("Error leyendo lead: chat_id=%s", cid)
        raise


def upsert_lead(
    chat_id: str,
    lead_record: LeadFields | Mapping[str, str | None],
    estado: str | None = None,
) -> bool:
    """Escribe o fusiona fila en `leads`. Devuelve False si falla (p. ej. hoja mal configurada)."""
    cid = _norm_chat_id(chat_id)
    try:
        ws = _worksheet("leads")
        rows = ws.get_all_values()
        if not rows:
            raise ValueError("leads: hoja vacía o sin encabezados")

        headers = [h.strip() for h in rows[0]]
        col_map = _header_index_map(headers)
        for h in LEADS_HEADERS:
            if h not in col_map:
                raise ValueError(f"leads: falta columna {h!r}")

        data = _lead_field_values(lead_record)
        row_idx: int | None = None
        for i, row in enumerate(rows[1:], start=2):
            if len(row) <= col_map["chat_id"]:
                continue
            if _norm_chat_id(row[col_map["chat_id"]]) == cid:
                row_idx = i
                break

        now = datetime.now(timezone.utc).isoformat()

        if row_idx is None:
            estado_val = estado if estado is not None else "en_curso"
            row_out = [""] * len(headers)
            row_out[col_map["chat_id"]] = cid
            for key in LEAD_DATA_KEYS:
                inc = _incoming_value(data.get(key))
                if inc is not None:
                    row_out[col_map[key]] = inc
            row_out[col_map["estado"]] = estado_val
            row_out[col_map["created_at"]] = now
            row_out[col_map["updated_at"]] = now
            ws.append_row(row_out, value_input_option=ValueInputOption.user_entered)
            filled = sum(
                1 for k in LEAD_DATA_KEYS if not _is_blank_cell(row_out[col_map[k]])
            )
            logger.info(
                "Lead actualizado: chat_id=%s, campos_con_valor=%s/9", cid, filled
            )
            return True

        # Update: solo rellenar celdas vacías con valores nuevos no vacíos; nunca borrar.
        row_values = list(rows[row_idx - 1])
        while len(row_values) < len(headers):
            row_values.append("")

        updates: list[dict[str, Any]] = []
        for key in LEAD_DATA_KEYS:
            current = (
                row_values[col_map[key]].strip()
                if col_map[key] < len(row_values)
                else ""
            )
            inc = _incoming_value(data.get(key))
            if inc is None or not _is_blank_cell(current):
                continue
            row_values[col_map[key]] = inc
            cell_ref = f"{_col_a1(col_map[key])}{row_idx}"
            updates.append({"range": cell_ref, "values": [[inc]]})

        if estado is not None:
            cell_ref = f"{_col_a1(col_map['estado'])}{row_idx}"
            updates.append({"range": cell_ref, "values": [[estado]]})
            row_values[col_map["estado"]] = estado

        cell_ref_updated = f"{_col_a1(col_map['updated_at'])}{row_idx}"
        updates.append({"range": cell_ref_updated, "values": [[now]]})
        row_values[col_map["updated_at"]] = now

        if updates:
            ws.batch_update(updates, value_input_option=ValueInputOption.user_entered)

        merged = {
            h: row_values[col_map[h]] if col_map[h] < len(row_values) else ""
            for h in headers
        }
        filled = _count_lead_fields_filled(merged)
        logger.info("Lead actualizado: chat_id=%s, campos_con_valor=%s/9", cid, filled)
        return True
    except Exception:
        logger.exception("Error upsert lead: chat_id=%s", cid)
        return False


def mark_conversation_closed(chat_id: str) -> None:
    cid = _norm_chat_id(chat_id)
    try:
        ws = _worksheet("conversaciones")
        rows = ws.get_all_values()
        if not rows:
            return
        headers = [h.strip() for h in rows[0]]
        col_map = _header_index_map(headers)
        if "chat_id" not in col_map or "estado" not in col_map:
            raise ValueError("conversaciones: faltan columnas chat_id o estado")

        chat_col = col_map["chat_id"]
        estado_col = col_map["estado"]
        batch: list[dict[str, Any]] = []
        for i, row in enumerate(rows[1:], start=2):
            if len(row) <= chat_col:
                continue
            if _norm_chat_id(row[chat_col]) != cid:
                continue
            cell_ref = f"{_col_a1(estado_col)}{i}"
            batch.append({"range": cell_ref, "values": [["cerrada"]]})

        if batch:
            ws.batch_update(batch, value_input_option=ValueInputOption.user_entered)
    except Exception:
        logger.exception("Error marcando conversación cerrada: chat_id=%s", cid)

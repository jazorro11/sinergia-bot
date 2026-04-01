#!/usr/bin/env python3
"""
Análisis de intervalos entre mensajes consecutivos del usuario (misma conversación).

Uso (desde la raíz del repo, con .env cargado como el bot):
  python scripts/analyze_message_intervals.py

Requiere las mismas variables de entorno que el bot (Sheets).

KPIs sugeridos para el piloto typing + debounce
-----------------------------------------------
- share_usuarios_con_burst: % de chat_id con al menos un par user→user con Δt < 15 s.
- p50 / p90 de esos Δt (segundos).
- Llamadas LLM por conversación (baseline vs piloto): logs o panel OpenAI.
- Calidad subjetiva: muestra de hilos antes/después.
- Quejas explícitas de lentitud o “no responde”.

Decisión go/no-go (resumen)
---------------------------
- Go si mejora calidad o bajan respuestas vacías al saludo, sin subir tokens agregados
  y sin quejas fuertes por espera.
- Ajustar MESSAGE_DEBOUNCE_SECONDS (p. ej. 5–8 s) o limitar acumulación al inicio del hilo si hace falta.
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from pathlib import Path

# Raíz del proyecto (padre de scripts/)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def main() -> None:
    if load_dotenv:
        load_dotenv(_ROOT / ".env")

    from bot import storage  # noqa: PLC0415 — tras dotenv

    ws = storage._worksheet("conversaciones")  # noqa: SLF001 — script interno
    rows = ws.get_all_values()
    if not rows:
        print("Hoja conversaciones vacía.")
        return

    headers = [h.strip() for h in rows[0]]
    col_map = storage._header_index_map(headers)  # noqa: SLF001
    for r in ("chat_id", "role", "timestamp"):
        if r not in col_map:
            print(f"Falta columna {r!r} en conversaciones.")
            return

    by_chat: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in rows[1:]:
        if len(row) <= col_map["chat_id"]:
            continue
        cid = storage._norm_chat_id(row[col_map["chat_id"]])  # noqa: SLF001
        role = row[col_map["role"]].strip() if len(row) > col_map["role"] else ""
        ts_raw = row[col_map["timestamp"]] if len(row) > col_map["timestamp"] else ""
        if role != "user":
            continue
        try:
            ts = int(str(ts_raw).strip())
        except ValueError:
            continue
        by_chat[cid].append((ts, "user"))

    for cid in by_chat:
        by_chat[cid].sort(key=lambda x: x[0])

    deltas: list[float] = []
    chats_with_burst_under_15: set[str] = set()
    for cid, seq in by_chat.items():
        for i in range(1, len(seq)):
            dt = seq[i][0] - seq[i - 1][0]
            if dt >= 0:
                deltas.append(float(dt))
                if dt < 15:
                    chats_with_burst_under_15.add(cid)

    n_chats = len(by_chat)
    n_burst = len(chats_with_burst_under_15)
    print("--- Intervalos entre mensajes user consecutivos (mismo chat_id) ---")
    print(f"Chats con al menos 2 mensajes user: {n_chats}")
    print(f"Pares user→user analizados: {len(deltas)}")
    if n_chats:
        print(
            f"Chats con algún par con Δt < 15 s: {n_burst} "
            f"({100.0 * n_burst / n_chats:.1f}% de chats con 2+ user)"
        )
    if deltas:
        print(f"Δt mín / máx (s): {min(deltas):.1f} / {max(deltas):.1f}")
        print(f"Δt p50 / p90 (s): {statistics.median(deltas):.1f} / {_p90(deltas):.1f}")
    else:
        print("No hay pares consecutivos user→user.")
    print()
    print("Si el % de chats con ráfagas < 15 s es bajo, debounce ~10 s aporta poco al agregado.")
    print()
    print("--- Piloto / go-no-go (checklist) ---")
    print("1. Desplegar TELEGRAM_TYPING_ENABLED + MESSAGE_DEBOUNCE_SECONDS según .env.example.")
    print("2. Recolectar logs [debounce] y [typing] y KPIs definidos en el docstring de este script.")
    print("3. Go si mejora calidad o bajan respuestas al solo-saludo sin subir tokens agregados.")


def _p90(values: list[float]) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    k = max(0, min(len(s) - 1, int(round(0.9 * (len(s) - 1)))))
    return s[k]


if __name__ == "__main__":
    main()

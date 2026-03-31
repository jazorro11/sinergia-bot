"""Unit tests for bot.extraction."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from bot.extraction import extract_lead_data


def _mock_completion_json(payload: str) -> MagicMock:
    msg = MagicMock()
    msg.content = payload
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@patch("bot.extraction.config.llm_extraction.chat.completions.create")
def test_extract_lead_data_partial_success(mock_create: MagicMock) -> None:
    partial = {
        "nombre": "Ana",
        "ciudad": "Medellín",
        "tipo_espacio": "Apartamento",
        "tipo_intervencion": None,
        "area_aprox": None,
        "situacion_actual": None,
        "fecha_deseada": None,
        "presupuesto": None,
        "alcance": None,
    }
    mock_create.return_value = _mock_completion_json(json.dumps(partial))
    history = [{"role": "user", "content": "Hola"}]
    record = extract_lead_data(history, 42)
    assert record is not None
    assert record.nombre == "Ana"
    assert record.ciudad == "Medellín"
    assert record.tipo_espacio == "Apartamento"
    assert record.tipo_intervencion is None
    assert record.area_aprox is None
    assert record.situacion_actual is None
    assert record.fecha_deseada is None
    assert record.presupuesto is None
    assert record.alcance is None


@patch("bot.extraction.config.llm_extraction.chat.completions.create")
def test_extract_lead_data_appends_merge_hint_when_lead_row_given(
    mock_create: MagicMock,
) -> None:
    partial = {
        "nombre": "Ana",
        "ciudad": None,
        "tipo_espacio": None,
        "tipo_intervencion": None,
        "area_aprox": None,
        "situacion_actual": None,
        "fecha_deseada": None,
        "presupuesto": None,
        "alcance": None,
    }
    mock_create.return_value = _mock_completion_json(json.dumps(partial))
    row = {
        "nombre": "Otros",
        "ciudad": "Cali",
        "tipo_espacio": None,
        "tipo_intervencion": None,
        "area_aprox": None,
        "situacion_actual": None,
        "fecha_deseada": None,
        "presupuesto": None,
        "alcance": None,
    }
    extract_lead_data([{"role": "user", "content": "Hola"}], 1, merge_from_lead_row=row)
    sys_msg = mock_create.call_args.kwargs["messages"][0]["content"]
    assert "Registro previo" in sys_msg
    assert "ciudad: Cali" in sys_msg


@patch("bot.extraction.config.llm_extraction.chat.completions.create")
def test_extract_lead_data_failure_returns_none_and_logs_error(
    mock_create: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock_create.side_effect = RuntimeError("quota exceeded")
    caplog.set_level("ERROR", logger="bot.extraction")
    out = extract_lead_data([{"role": "user", "content": "x"}], 1)
    assert out is None
    assert any(r.levelname == "ERROR" for r in caplog.records)

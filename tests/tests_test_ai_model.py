"""Admin-chosen Gemini model per store: reading it safely, and the scan using it."""
import time
from unittest.mock import MagicMock, patch

import pytest

from config.settings import GEMINI_MODEL
from core import ai_model
from modules.invoice_scan import ocr_service


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    ai_model.clear_cache()
    monkeypatch.setattr(ai_model, "ACTIVE_DB_BACKEND", "supabase")
    yield
    ai_model.clear_cache()


def _client(rows, seen=None):
    table = MagicMock()
    table.select.return_value = table
    table.in_.side_effect = lambda col, ids: (seen.append(ids) if seen is not None else None) or table
    table.execute.return_value = MagicMock(data=rows)
    client = MagicMock()
    client.table.return_value = table
    return client


def _use(monkeypatch, client):
    monkeypatch.setattr("core.supabase_client.get_supabase_client", lambda: client)


def test_name_check():
    for good in ("gemini-3.6-flash", "models/gemini-2.5-pro", "gemini_x.1"):
        assert ai_model.is_valid_model_name(good)
    for bad in ("", "a b", "x;y", "-x", None, "x" * 90):
        assert not ai_model.is_valid_model_name(bad)


def test_store_row_beats_all_stores_row_beats_normal(monkeypatch):
    rows = [{"store_id": 0, "model": "all-model"}, {"store_id": 7, "model": "own-model"}]
    _use(monkeypatch, _client(rows))
    assert ai_model.model_for_store(7) == "own-model"
    assert ai_model.model_for_store(8) == "all-model"
    ai_model.clear_cache()
    _use(monkeypatch, _client([]))
    assert ai_model.model_for_store(7) == GEMINI_MODEL


def test_only_the_store_default_and_level_rows_are_asked_for(monkeypatch):
    seen = []
    _use(monkeypatch, _client([], seen))
    ai_model.model_for_store(7)
    assert seen == [[7, 0, -1, -2]]


def test_read_once_a_minute(monkeypatch):
    client = _client([{"store_id": 7, "model": "own-model"}])
    _use(monkeypatch, client)
    for _ in range(5):
        assert ai_model.model_for_store(7) == "own-model"
    assert client.table.call_count == 1
    ai_model._cache[7] = (time.monotonic() - 61, "own-model", True)         # a minute later: read again
    ai_model.model_for_store(7)
    assert client.table.call_count == 2


def test_any_problem_means_the_normal_model(monkeypatch):
    broken = MagicMock()
    broken.table.side_effect = RuntimeError("no table")
    _use(monkeypatch, broken)
    assert ai_model.model_for_store(7) == GEMINI_MODEL
    ai_model.clear_cache()
    _use(monkeypatch, _client([{"store_id": 7, "model": "bad name;x"}]))      # a strange name is ignored
    assert ai_model.model_for_store(7) == GEMINI_MODEL


def test_sqlite_backend_never_asks(monkeypatch):
    monkeypatch.setattr(ai_model, "ACTIVE_DB_BACKEND", "sqlite")
    assert ai_model.model_for_store(7) == GEMINI_MODEL


def test_scan_uses_the_stores_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    from tests.test_ocr_service import TestExtractMedicinesFromFile, make_png_file_obj, valid_combined_json
    helper = TestExtractMedicinesFromFile()
    mock_client = helper._make_mock_client(valid_combined_json(2))
    monkeypatch.setattr("core.session.get_current_store_id", lambda: 7)
    monkeypatch.setattr(ai_model, "model_for_store", lambda store_id: f"model-of-{store_id}")
    with patch("modules.invoice_scan.ocr_service._build_genai_client", return_value=mock_client):
        result = ocr_service.extract_medicines_from_file(make_png_file_obj())
    assert result["model"] == "model-of-7"
    assert mock_client.models.generate_content.call_args.kwargs["model"] == "model-of-7"


def test_scan_without_a_session_uses_the_normal_model():
    assert ocr_service._resolve_model() == GEMINI_MODEL


def test_store_on_a_level_follows_that_levels_current_name(monkeypatch):
    rows = [{"store_id": 7, "model": "@high"}, {"store_id": -1, "model": "big-model"},
            {"store_id": -2, "model": "small-model"}, {"store_id": 8, "model": "@medium"}]
    _use(monkeypatch, _client(rows))
    assert ai_model.model_for_store(7) == "big-model"
    assert ai_model.model_for_store(8) == "small-model"


def test_level_without_a_name_falls_back(monkeypatch):
    assert ai_model.choose_model({7: "@high"}, 7) is None
    assert ai_model.choose_model({7: "@high", 0: "all-model"}, 7) == "all-model"
    assert ai_model.choose_model({0: "@medium", -2: "small"}, 9) == "small"
    assert ai_model.choose_model({7: "own", -1: "big"}, 7) == "own"
    _use(monkeypatch, _client([{"store_id": 7, "model": "@high"}]))
    assert ai_model.model_for_store(7) == GEMINI_MODEL


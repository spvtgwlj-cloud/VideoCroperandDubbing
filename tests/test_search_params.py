"""智能检索参数持久化单测。"""

import json

from core.search_params import (
    DEFAULT_SEARCH_PARAMS, load_search_params, save_search_params,
)


def test_load_missing_returns_defaults(tmp_path):
    assert load_search_params(str(tmp_path / "missing.json")) == \
        DEFAULT_SEARCH_PARAMS


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "params.json")
    data = {
        "min_dur": 45,
        "max_dur": 90,
        "merge_gap": 1.5,
        "top_k": 5,
        "deep_mode": True,
        "force_export": True,
        "allow_relaxed_fallback": True,
    }
    save_search_params(data, path)
    loaded = load_search_params(path)
    for key, value in data.items():
        assert loaded[key] == value


def test_load_invalid_json_returns_defaults(tmp_path):
    path = tmp_path / "params.json"
    path.write_text("not json", encoding="utf-8")
    assert load_search_params(str(path)) == DEFAULT_SEARCH_PARAMS


def test_load_clamps_out_of_range_values(tmp_path):
    path = tmp_path / "params.json"
    path.write_text(json.dumps({
        "min_dur": 9999,
        "max_dur": 1,
        "merge_gap": -5.0,
        "top_k": 0,
        "deep_mode": "yes",
    }), encoding="utf-8")
    loaded = load_search_params(str(path))
    assert loaded["min_dur"] == DEFAULT_SEARCH_PARAMS["min_dur"]
    assert loaded["max_dur"] == DEFAULT_SEARCH_PARAMS["max_dur"]
    assert loaded["merge_gap"] == 0.0
    assert loaded["top_k"] == 1
    assert loaded["deep_mode"] is True


def test_load_ignores_wrong_types(tmp_path):
    path = tmp_path / "params.json"
    path.write_text(json.dumps({
        "min_dur": "abc",
        "max_dur": None,
        "merge_gap": "x",
        "top_k": True,
    }), encoding="utf-8")
    loaded = load_search_params(str(path))
    assert loaded["min_dur"] == DEFAULT_SEARCH_PARAMS["min_dur"]
    assert loaded["max_dur"] == DEFAULT_SEARCH_PARAMS["max_dur"]
    assert loaded["merge_gap"] == DEFAULT_SEARCH_PARAMS["merge_gap"]
    assert loaded["top_k"] == DEFAULT_SEARCH_PARAMS["top_k"]

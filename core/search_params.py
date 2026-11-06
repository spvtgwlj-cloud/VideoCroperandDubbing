"""智能检索参数持久化（零 Qt 依赖）。"""

import json
import os

from .smart_search import CACHE_ROOT

SEARCH_PARAMS_PATH = os.path.join(CACHE_ROOT, "search_params.json")

DEFAULT_SEARCH_PARAMS: dict = {
    "min_dur": 30,
    "max_dur": 120,
    "merge_gap": 2.0,
    "top_k": 3,
    "deep_mode": True,  # 原默认 False
    "force_export": False,
    "allow_relaxed_fallback": False,
}


def _coerce_int(value, default: int, minimum: int, maximum: int) -> int:
    """把值转成限定范围内的整数；非法值返回默认值。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _coerce_float(value, default: float, minimum: float,
                  maximum: float) -> float:
    """把值转成限定范围内的浮点数；非法值返回默认值。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _coerce_bool(value, default: bool) -> bool:
    """只接受布尔值或 0/1；其它类型返回默认值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return default


def load_search_params(path: str | None = None) -> dict:
    """读取参数文件；不存在、损坏或字段非法时回退到默认值。"""
    path = path or SEARCH_PARAMS_PATH
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return dict(DEFAULT_SEARCH_PARAMS)
    if not isinstance(data, dict):
        return dict(DEFAULT_SEARCH_PARAMS)

    params = dict(DEFAULT_SEARCH_PARAMS)
    params["min_dur"] = _coerce_int(
        data.get("min_dur"), DEFAULT_SEARCH_PARAMS["min_dur"], 1, 600,
    )
    params["max_dur"] = _coerce_int(
        data.get("max_dur"), DEFAULT_SEARCH_PARAMS["max_dur"], 5, 3600,
    )
    params["merge_gap"] = _coerce_float(
        data.get("merge_gap"), DEFAULT_SEARCH_PARAMS["merge_gap"],
        0.0, 60.0,
    )
    params["top_k"] = _coerce_int(
        data.get("top_k"), DEFAULT_SEARCH_PARAMS["top_k"], 1, 100,
    )
    params["deep_mode"] = _coerce_bool(
        data.get("deep_mode"), DEFAULT_SEARCH_PARAMS["deep_mode"],
    )
    params["force_export"] = _coerce_bool(
        data.get("force_export"), DEFAULT_SEARCH_PARAMS["force_export"],
    )
    params["allow_relaxed_fallback"] = _coerce_bool(
        data.get("allow_relaxed_fallback"),
        DEFAULT_SEARCH_PARAMS["allow_relaxed_fallback"],
    )

    if params["min_dur"] >= params["max_dur"]:
        params["min_dur"] = DEFAULT_SEARCH_PARAMS["min_dur"]
        params["max_dur"] = DEFAULT_SEARCH_PARAMS["max_dur"]
    return params


def save_search_params(params: dict, path: str | None = None) -> None:
    """保存参数；只写入已知字段，未知字段忽略。"""
    path = path or SEARCH_PARAMS_PATH
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload = {
        key: params.get(key, DEFAULT_SEARCH_PARAMS[key])
        for key in DEFAULT_SEARCH_PARAMS
    }
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

"""
LSTM 수위 예측 — 전처리 모듈
- 정규화 (Min-Max Scaling)
- 시계열 윈도우 생성
- 특성 엔지니어링 (시간 cyclical encoding)
"""

import json
import math
import os

WINDOW_SIZE = 24   # 24시간 이력
HORIZON = 12       # 12시간 예측
NUM_FEATURES = 6   # water_level, level_ratio, rain_prob, rain_amount, hour_sin, hour_cos

FEATURE_NAMES = [
    "water_level",
    "level_ratio",
    "rain_probability",
    "rain_amount",
    "hour_sin",
    "hour_cos",
]

DEFAULT_SCALER = {
    "water_level":      {"min": 0.0, "max": 500.0},
    "level_ratio":      {"min": 0.0, "max": 100.0},
    "rain_probability": {"min": 0.0, "max": 100.0},
    "rain_amount":      {"min": 0.0, "max": 50.0},
    "hour_sin":         {"min": -1.0, "max": 1.0},
    "hour_cos":         {"min": -1.0, "max": 1.0},
}


def load_scaler(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_SCALER


def save_scaler(scaler, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scaler, f, indent=2, ensure_ascii=False)


def fit_scaler(all_records):
    """학습 데이터에서 min/max를 계산한다."""
    scaler = {}
    for feat in FEATURE_NAMES:
        vals = [r[feat] for r in all_records if r.get(feat) is not None]
        if vals:
            scaler[feat] = {"min": min(vals), "max": max(vals)}
        else:
            scaler[feat] = DEFAULT_SCALER[feat]
    for feat in ("hour_sin", "hour_cos"):
        scaler[feat] = {"min": -1.0, "max": 1.0}
    return scaler


def normalize(value, feat_name, scaler):
    s = scaler.get(feat_name, DEFAULT_SCALER.get(feat_name, {"min": 0, "max": 1}))
    mn, mx = s["min"], s["max"]
    if mx == mn:
        return 0.0
    return (value - mn) / (mx - mn)


def denormalize(value, feat_name, scaler):
    s = scaler.get(feat_name, DEFAULT_SCALER.get(feat_name, {"min": 0, "max": 1}))
    mn, mx = s["min"], s["max"]
    return value * (mx - mn) + mn


def hour_encoding(hour):
    """시간을 sin/cos cyclical feature로 변환 (0~23)."""
    rad = 2 * math.pi * hour / 24.0
    return math.sin(rad), math.cos(rad)


def build_feature_row(reading, weather_map, hour):
    """한 시점의 특성 벡터를 생성한다."""
    h_sin, h_cos = hour_encoding(hour)
    rain_prob = 0.0
    rain_amount = 0.0
    if weather_map:
        w = weather_map.get(hour, {})
        rain_prob = w.get("rain_probability", 0.0) or 0.0
        rain_amount = float(w.get("rain_amount", 0) or 0)
    return {
        "water_level": reading.get("water_level", 0.0) or 0.0,
        "level_ratio": reading.get("level_ratio", 0.0) or 0.0,
        "rain_probability": rain_prob,
        "rain_amount": rain_amount,
        "hour_sin": h_sin,
        "hour_cos": h_cos,
    }


def normalize_row(row, scaler):
    return [normalize(row[feat], feat, scaler) for feat in FEATURE_NAMES]


def create_windows(feature_rows, scaler):
    """시계열 데이터를 (input_window, target) 쌍으로 변환한다.
    feature_rows: list of dicts (FEATURE_NAMES 키)
    반환: (inputs, targets) — inputs: list of [WINDOW_SIZE x NUM_FEATURES],
                              targets: list of [HORIZON] (water_level 정규화값)
    """
    inputs, targets = [], []
    total = len(feature_rows)
    for i in range(total - WINDOW_SIZE - HORIZON + 1):
        window = feature_rows[i : i + WINDOW_SIZE]
        target_slice = feature_rows[i + WINDOW_SIZE : i + WINDOW_SIZE + HORIZON]
        inp = [normalize_row(r, scaler) for r in window]
        tgt = [normalize(r["water_level"], "water_level", scaler) for r in target_slice]
        inputs.append(inp)
        targets.append(tgt)
    return inputs, targets


def prepare_inference_input(feature_rows, scaler):
    """추론용 입력: 마지막 WINDOW_SIZE 시점의 정규화된 배열.
    반환: list of [WINDOW_SIZE x NUM_FEATURES] (단일 샘플)
    None을 반환하면 데이터 부족.
    """
    if len(feature_rows) < WINDOW_SIZE:
        return None
    window = feature_rows[-WINDOW_SIZE:]
    return [normalize_row(r, scaler) for r in window]


def parse_hour_from_iso(iso_str):
    """ISO 문자열에서 시(hour)를 추출한다."""
    try:
        if "T" in iso_str:
            time_part = iso_str.split("T")[1]
        else:
            time_part = iso_str.split(" ")[1] if " " in iso_str else "00:00"
        return int(time_part[:2])
    except (IndexError, ValueError):
        return 0

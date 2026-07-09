"""
LSTM 수위 예측 — 전처리 모듈 v2
- 정규화 (Min-Max Scaling)
- 시계열 윈도우 생성
- 특성 엔지니어링 (10개 특성)
- 선형 보간 결측 처리
"""

import json
import math
import os

WINDOW_SIZE = 24
HORIZON = 12
NUM_FEATURES = 10

FEATURE_NAMES = [
    "water_level",
    "level_ratio",
    "rain_probability",
    "rain_amount",
    "hour_sin",
    "hour_cos",
    "prev_day_level",
    "moving_avg_24h",
    "level_change_rate",
    "is_weekend",
]

DEFAULT_SCALER = {
    "water_level":       {"min": 0.0, "max": 500.0},
    "level_ratio":       {"min": 0.0, "max": 100.0},
    "rain_probability":  {"min": 0.0, "max": 100.0},
    "rain_amount":       {"min": 0.0, "max": 50.0},
    "hour_sin":          {"min": -1.0, "max": 1.0},
    "hour_cos":          {"min": -1.0, "max": 1.0},
    "prev_day_level":    {"min": 0.0, "max": 500.0},
    "moving_avg_24h":    {"min": 0.0, "max": 500.0},
    "level_change_rate": {"min": -1.0, "max": 1.0},
    "is_weekend":        {"min": 0.0, "max": 1.0},
}


def load_scaler(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        for feat in FEATURE_NAMES:
            if feat not in loaded:
                loaded[feat] = DEFAULT_SCALER[feat]
        return loaded
    return dict(DEFAULT_SCALER)


def save_scaler(scaler, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scaler, f, indent=2, ensure_ascii=False)


def fit_scaler(all_records):
    scaler = {}
    for feat in FEATURE_NAMES:
        vals = [r[feat] for r in all_records if r.get(feat) is not None]
        if vals:
            mn, mx = min(vals), max(vals)
            if mn == mx:
                scaler[feat] = DEFAULT_SCALER[feat]
            else:
                scaler[feat] = {"min": mn, "max": mx}
        else:
            scaler[feat] = DEFAULT_SCALER[feat]
    for feat in ("hour_sin", "hour_cos"):
        scaler[feat] = {"min": -1.0, "max": 1.0}
    scaler["is_weekend"] = {"min": 0.0, "max": 1.0}
    return scaler


def normalize(value, feat_name, scaler):
    s = scaler.get(feat_name, DEFAULT_SCALER.get(feat_name, {"min": 0, "max": 1}))
    mn, mx = s["min"], s["max"]
    if mx == mn:
        return 0.0
    return max(0.0, min(1.0, (value - mn) / (mx - mn)))


def denormalize(value, feat_name, scaler):
    s = scaler.get(feat_name, DEFAULT_SCALER.get(feat_name, {"min": 0, "max": 1}))
    mn, mx = s["min"], s["max"]
    return value * (mx - mn) + mn


def hour_encoding(hour):
    rad = 2 * math.pi * hour / 24.0
    return math.sin(rad), math.cos(rad)


def interpolate_gaps(values, max_gap=3):
    """선형 보간으로 결측(None) 채움. max_gap 초과 연속 결측은 제외 표시."""
    result = list(values)
    n = len(result)
    i = 0
    while i < n:
        if result[i] is None:
            start = i
            while i < n and result[i] is None:
                i += 1
            gap_len = i - start
            if gap_len > max_gap:
                continue
            left = result[start - 1] if start > 0 else None
            right = result[i] if i < n else None
            if left is not None and right is not None:
                for j in range(gap_len):
                    t = (j + 1) / (gap_len + 1)
                    result[start + j] = left + t * (right - left)
            elif left is not None:
                for j in range(gap_len):
                    result[start + j] = left
            elif right is not None:
                for j in range(gap_len):
                    result[start + j] = right
        else:
            i += 1
    return result


def detect_outliers(levels, threshold=0.5):
    """수위가 이전 대비 threshold(50%) 이상 급변하면 이상치로 표시."""
    flags = [False] * len(levels)
    for i in range(1, len(levels)):
        if levels[i] is None or levels[i - 1] is None:
            continue
        if levels[i - 1] == 0:
            continue
        change = abs(levels[i] - levels[i - 1]) / abs(levels[i - 1])
        if change > threshold:
            flags[i] = True
    return flags


def build_feature_row(reading, weather_map, hour, prev_level=None, avg_24h=None, weekday=0):
    h_sin, h_cos = hour_encoding(hour)
    rain_prob = 0.0
    rain_amount = 0.0
    if weather_map:
        w = weather_map.get(hour, {})
        rain_prob = w.get("rain_probability", 0.0) or 0.0
        rain_amount = float(w.get("rain_amount", 0) or 0)

    wl = reading.get("water_level") or 0.0
    lr = reading.get("level_ratio") or 0.0

    change_rate = 0.0
    if prev_level is not None and prev_level > 0:
        change_rate = (wl - prev_level) / prev_level

    return {
        "water_level": wl,
        "level_ratio": lr,
        "rain_probability": rain_prob,
        "rain_amount": rain_amount,
        "hour_sin": h_sin,
        "hour_cos": h_cos,
        "prev_day_level": prev_level if prev_level is not None else wl,
        "moving_avg_24h": avg_24h if avg_24h is not None else wl,
        "level_change_rate": max(-1.0, min(1.0, change_rate)),
        "is_weekend": 1.0 if weekday >= 5 else 0.0,
    }


def normalize_row(row, scaler):
    return [normalize(row[feat], feat, scaler) for feat in FEATURE_NAMES]


def create_windows(feature_rows, scaler):
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
    if len(feature_rows) < WINDOW_SIZE:
        return None
    window = feature_rows[-WINDOW_SIZE:]
    return [normalize_row(r, scaler) for r in window]


def parse_hour_from_iso(iso_str):
    try:
        if "T" in iso_str:
            time_part = iso_str.split("T")[1]
        else:
            time_part = iso_str.split(" ")[1] if " " in iso_str else "00:00"
        return int(time_part[:2])
    except (IndexError, ValueError):
        return 0


def parse_weekday_from_iso(iso_str):
    """ISO 문자열에서 요일(0=월~6=일)을 추출."""
    try:
        date_str = iso_str[:10]
        parts = date_str.split("-")
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        import datetime
        return datetime.date(y, m, d).weekday()
    except (IndexError, ValueError):
        return 0

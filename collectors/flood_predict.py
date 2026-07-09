"""
AI 침수 예측 v2 — LSTM ONNX 앙상블 추론
- 앙상블 평균 예측 (3개 모델)
- 잔차 기반 ±σ 신뢰구간
- 최소 12건 이상 데이터 필요 (행복제 패딩 제거)
- 선형 보간 결측 처리
"""

import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ML_DIR = os.path.join(BASE_DIR, "ml")
sys.path.insert(0, BASE_DIR)

from ml.preprocess import (
    FEATURE_NAMES, HORIZON, NUM_FEATURES, WINDOW_SIZE,
    build_feature_row, denormalize, detect_outliers,
    interpolate_gaps, load_scaler, normalize_row,
    parse_hour_from_iso, parse_weekday_from_iso,
    prepare_inference_input,
)

KST = timezone(timedelta(hours=9))
MODEL_VERSION = "v2"
MIN_READINGS = 12


def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()


def sb_query(table, params=""):
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_KEY")
    if not sb_url or not sb_key:
        return []
    url = f"{sb_url}/rest/v1/{table}?{params}"
    req = urllib.request.Request(
        url, headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        return []


def sb_insert(table, records):
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_KEY")
    if not sb_url or not sb_key or not records:
        return 0
    body = json.dumps(records, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{sb_url}/rest/v1/{table}", data=body,
        headers={
            "apikey": sb_key, "Authorization": f"Bearer {sb_key}",
            "Content-Type": "application/json", "Prefer": "return=minimal",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return len(records) if resp.status in (200, 201) else 0
    except Exception:
        return 0


def report_health(status, count, error=None):
    sb_insert("collector_health", [{
        "collector": "flood_predict",
        "status": status,
        "record_count": count,
        "error_message": error,
        "collected_at": datetime.now(KST).isoformat(),
    }])


def classify_status(ratio):
    if ratio >= 80:
        return "danger"
    if ratio >= 50:
        return "warning"
    return "safe"


def load_ensemble_models():
    """앙상블 ONNX 모델을 로드. 없으면 단일 model.onnx 폴백."""
    try:
        import onnxruntime as ort
    except ImportError:
        return None

    sessions = []
    for i in range(3):
        path = os.path.join(ML_DIR, f"model_ensemble_{i}.onnx")
        if os.path.exists(path):
            sessions.append(ort.InferenceSession(path))

    if sessions:
        return sessions

    single_path = os.path.join(ML_DIR, "model.onnx")
    if os.path.exists(single_path):
        return [ort.InferenceSession(single_path)]

    return None


def compute_residual_confidence(station, sb_query_fn):
    """최근 7일 예측 vs 실측 잔차로 시간대별 표준편차를 계산."""
    residuals_by_hour = {}
    for h in range(1, HORIZON + 1):
        residuals_by_hour[h] = []

    preds = sb_query_fn(
        "flood_predictions",
        f"select=prediction_hour,predicted_level,target_time"
        f"&station=eq.{station}&order=predicted_at.desc&limit=252"
    )

    if not preds:
        return None

    for p in preds:
        target_time = p.get("target_time", "")
        pred_level = p.get("predicted_level", 0)
        hour = p.get("prediction_hour", 1)

        target_date = target_time[:10] if target_time else ""
        if not target_date:
            continue

        actuals = sb_query_fn(
            "river_readings",
            f"select=water_level,measured_at&station=eq.{station}"
            f"&measured_at=gte.{target_date}&limit=1"
        )
        if actuals:
            actual_level = actuals[0].get("water_level", 0)
            if actual_level and actual_level > 0:
                residual = pred_level - actual_level
                if hour in residuals_by_hour:
                    residuals_by_hour[hour].append(residual)

    result = {}
    for h in range(1, HORIZON + 1):
        resids = residuals_by_hour.get(h, [])
        if len(resids) >= 3:
            mean_r = sum(resids) / len(resids)
            var = sum((r - mean_r) ** 2 for r in resids) / len(resids)
            std = math.sqrt(var)
            result[h] = {"mean_bias": round(mean_r, 2), "std": round(std, 2), "n": len(resids)}
        else:
            result[h] = None
    return result


def main():
    import numpy as np

    print("=" * 50)
    print("🧠 AI 침수 예측 v2 (앙상블 LSTM)")
    print("=" * 50)

    load_env()

    sessions = load_ensemble_models()
    if sessions is None:
        print("⚠️  모델 없음 — 학습 필요 (python ml/train_lstm.py)")
        report_health("skip", 0, "no model found")
        return

    scaler_path = os.path.join(ML_DIR, "scaler_params.json")
    scaler = load_scaler(scaler_path)

    meta_path = os.path.join(ML_DIR, "model_meta.json")
    model_ver = MODEL_VERSION
    expected_features = NUM_FEATURES
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
            model_ver = meta.get("model_version", MODEL_VERSION)
            expected_features = meta.get("num_features", NUM_FEATURES)

    print(f"✅ 모델 로드 완료 (version: {model_ver}, 앙상블: {len(sessions)}개, 특성: {expected_features}개)")

    print("\n📥 최근 수위 데이터 조회...")
    readings = sb_query(
        "river_readings",
        "select=station,river,water_level,embankment_height,level_ratio,measured_at"
        "&order=measured_at.desc&limit=1000"
    )
    print(f"  → {len(readings)}건 수신")

    if not readings:
        print("❌ 수위 데이터 없음")
        report_health("error", 0, "no river_readings data")
        return

    today = datetime.now(KST).strftime("%Y-%m-%d")
    print(f"📥 기상 예보 조회 ({today})...")
    weather = sb_query(
        "weather_forecasts",
        f"select=river,forecast_date,forecast_hour,rain_probability,rain_amount"
        f"&forecast_date=eq.{today}&limit=500"
    )
    rain_active = sum(1 for w in weather if (w.get("rain_probability") or 0) > 0)
    print(f"  → {len(weather)}건 수신 (강수확률>0: {rain_active}건)")

    stations = {}
    for r in readings:
        stn = r.get("station", "unknown")
        if stn not in stations:
            stations[stn] = {
                "river": r.get("river", ""),
                "embankment_height": r.get("embankment_height", 500),
                "readings": [],
            }
        stations[stn]["readings"].append(r)

    for info in stations.values():
        info["readings"].sort(key=lambda x: x.get("measured_at", ""))

    now = datetime.now(KST)
    predicted_at = now.isoformat()
    total_saved = 0
    all_predictions = []

    print(f"\n🔮 {len(stations)}개 관측소 예측 중...")
    for stn, info in stations.items():
        stn_readings = info["readings"]
        river = info["river"]
        emb_height = info["embankment_height"] or 500

        if len(stn_readings) < MIN_READINGS:
            print(f"  ⚠️  {stn}: {len(stn_readings)}건 (최소 {MIN_READINGS}건 필요, 건너뜀)")
            continue

        raw_levels = [r.get("water_level") for r in stn_readings]
        outlier_flags = detect_outliers(raw_levels)
        for i, is_outlier in enumerate(outlier_flags):
            if is_outlier:
                raw_levels[i] = None
        interpolated = interpolate_gaps(raw_levels)

        weather_by_hour = {}
        for w in weather:
            if w.get("river") != river:
                continue
            hour_str = w.get("forecast_hour", "00:00")
            try:
                hour = int(hour_str.split(":")[0]) if ":" in str(hour_str) else int(hour_str)
            except (ValueError, TypeError):
                hour = 0
            weather_by_hour[hour] = w

        feature_rows = []
        level_history = []
        for idx, r in enumerate(stn_readings):
            wl = interpolated[idx]
            if wl is None:
                continue

            r_copy = dict(r)
            r_copy["water_level"] = wl

            measured = r.get("measured_at", r.get("collected_at", ""))
            hour = parse_hour_from_iso(measured)
            weekday = parse_weekday_from_iso(measured)

            prev_level = level_history[-24] if len(level_history) >= 24 else (level_history[0] if level_history else wl)
            avg_24h = sum(level_history[-24:]) / len(level_history[-24:]) if level_history else wl

            feat = build_feature_row(r_copy, weather_by_hour, hour, prev_level, avg_24h, weekday)
            feature_rows.append(feat)
            level_history.append(wl)

        if len(feature_rows) < WINDOW_SIZE:
            print(f"  ⚠️  {stn}: 보간 후 {len(feature_rows)}건 (윈도우 {WINDOW_SIZE} 미달, 건너뜀)")
            continue

        inp = prepare_inference_input(feature_rows, scaler)
        if inp is None:
            continue

        input_array = np.array([inp], dtype=np.float32)

        if expected_features != NUM_FEATURES:
            if input_array.shape[2] > expected_features:
                input_array = input_array[:, :, :expected_features]
            elif input_array.shape[2] < expected_features:
                pad_width = expected_features - input_array.shape[2]
                input_array = np.pad(input_array, ((0,0),(0,0),(0,pad_width)), constant_values=0)

        ensemble_preds = []
        for session in sessions:
            result = session.run(None, {"input": input_array})
            ensemble_preds.append(result[0][0])

        pred_normalized = np.mean(ensemble_preds, axis=0)
        pred_std = np.std(ensemble_preds, axis=0) if len(ensemble_preds) > 1 else np.zeros_like(pred_normalized)

        residual_stats = compute_residual_confidence(stn, sb_query)
        data_completeness = min(1.0, len(stn_readings) / WINDOW_SIZE)

        records = []
        for h in range(HORIZON):
            pred_level = denormalize(float(pred_normalized[h]), "water_level", scaler)
            pred_level = max(0.0, pred_level)
            pred_ratio = (pred_level / emb_height) * 100 if emb_height > 0 else 0
            pred_ratio = max(0.0, min(100.0, pred_ratio))
            target_time = (now + timedelta(hours=h + 1)).isoformat()

            confidence_info = {}
            if residual_stats and residual_stats.get(h + 1):
                rs = residual_stats[h + 1]
                confidence_info = {
                    "ci_std": rs["std"],
                    "ci_bias": rs["mean_bias"],
                    "ci_lower": round(max(0, pred_level - rs["std"]), 2),
                    "ci_upper": round(pred_level + rs["std"], 2),
                    "ci_samples": rs["n"],
                }
                confidence = round(max(0.1, min(1.0, 1.0 - rs["std"] / max(pred_level, 1.0))), 2)
            else:
                ensemble_std_cm = denormalize(float(pred_std[h]), "water_level", scaler) if len(ensemble_preds) > 1 else 0
                confidence_info = {
                    "ci_std": round(ensemble_std_cm, 2),
                    "ci_lower": round(max(0, pred_level - ensemble_std_cm), 2),
                    "ci_upper": round(pred_level + ensemble_std_cm, 2),
                    "ci_samples": 0,
                }
                confidence = round(max(0.3, data_completeness * (1.0 - (h + 1) * 0.03)), 2)

            records.append({
                "station": stn,
                "river": river,
                "prediction_hour": h + 1,
                "predicted_level": round(pred_level, 2),
                "predicted_ratio": round(pred_ratio, 2),
                "predicted_status": classify_status(pred_ratio),
                "confidence": confidence,
                "model_version": model_ver,
                "input_snapshot": json.dumps(confidence_info, ensure_ascii=False),
                "predicted_at": predicted_at,
                "target_time": target_time,
            })

        saved = sb_insert("flood_predictions", records)
        total_saved += saved

        status_6h = records[5]["predicted_status"] if len(records) > 5 else "?"
        ratio_6h = records[5]["predicted_ratio"] if len(records) > 5 else 0
        ci = json.loads(records[5]["input_snapshot"]) if len(records) > 5 else {}
        ci_str = f" ±{ci.get('ci_std', '?')}cm" if ci.get("ci_std") else ""
        emoji = {"danger": "🔴", "warning": "🟡", "safe": "🟢"}.get(status_6h, "⚪")
        print(f"  {emoji} {stn} ({river}): 6h 예측 {ratio_6h:.1f}% [{status_6h}]{ci_str}")
        all_predictions.extend(records)

    print(f"\n💾 Supabase 저장: {total_saved}건")

    danger_count = sum(1 for p in all_predictions if p["predicted_status"] == "danger")
    warning_count = sum(1 for p in all_predictions if p["predicted_status"] == "warning")
    if danger_count:
        print(f"  🔴 위험 예측: {danger_count}건")
    if warning_count:
        print(f"  🟡 주의 예측: {warning_count}건")

    report_health("ok", total_saved)
    print("✅ AI 침수 예측 v2 완료")


if __name__ == "__main__":
    main()

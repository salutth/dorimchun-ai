"""
AI 침수 예측 — LSTM ONNX 추론 (Phase 3-1)
- 입력: Supabase 수위 데이터 + 기상 예보 (최근 24시간)
- 처리: ONNX Runtime으로 LSTM 모델 추론
- 출력: Supabase flood_predictions 테이블 저장

매시간 GitHub Actions에서 실행.
model.onnx가 없으면 경고 후 정상 종료 (exit 0).
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ML_DIR = os.path.join(BASE_DIR, "ml")
sys.path.insert(0, BASE_DIR)

from ml.preprocess import (
    FEATURE_NAMES, HORIZON, WINDOW_SIZE,
    build_feature_row, denormalize, load_scaler,
    normalize_row, parse_hour_from_iso, prepare_inference_input,
)

KST = timezone(timedelta(hours=9))
MODEL_VERSION = "v1"
MIN_READINGS = 3


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
        url,
        headers={
            "apikey": sb_key,
            "Authorization": f"Bearer {sb_key}",
        },
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
        f"{sb_url}/rest/v1/{table}",
        data=body,
        headers={
            "apikey": sb_key,
            "Authorization": f"Bearer {sb_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
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


def compute_confidence(prediction_hour, data_completeness):
    base = max(0.3, 1.0 - prediction_hour * 0.05)
    return round(base * data_completeness, 2)


def main():
    import numpy as np

    print("=" * 50)
    print("🧠 AI 침수 예측 (LSTM)")
    print("=" * 50)

    load_env()

    model_path = os.path.join(ML_DIR, "model.onnx")
    scaler_path = os.path.join(ML_DIR, "scaler_params.json")

    if not os.path.exists(model_path):
        print("⚠️  model.onnx 없음 — 학습이 필요합니다 (python ml/train_lstm.py)")
        report_health("skip", 0, "model.onnx not found")
        return

    try:
        import onnxruntime as ort
    except ImportError:
        print("⚠️  onnxruntime 미설치 — pip install -r requirements.txt")
        report_health("error", 0, "onnxruntime not installed")
        return

    scaler = load_scaler(scaler_path)
    session = ort.InferenceSession(model_path)

    meta_path = os.path.join(ML_DIR, "model_meta.json")
    model_ver = MODEL_VERSION
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
            model_ver = meta.get("model_version", MODEL_VERSION)

    print(f"✅ ONNX 모델 로드 완료 (version: {model_ver})")

    print("\n📥 최근 24시간 수위 데이터 조회...")
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
    print(f"  → {len(weather)}건 수신")

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
            print(f"  ⚠️  {stn}: {len(stn_readings)}건 (부족, 건너뜀)")
            continue

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
        for r in stn_readings:
            measured = r.get("measured_at", r.get("collected_at", ""))
            hour = parse_hour_from_iso(measured)
            feat = build_feature_row(r, weather_by_hour, hour)
            feature_rows.append(feat)

        if len(feature_rows) < WINDOW_SIZE:
            pad_count = WINDOW_SIZE - len(feature_rows)
            feature_rows = [feature_rows[0]] * pad_count + feature_rows

        inp = prepare_inference_input(feature_rows, scaler)
        if inp is None:
            print(f"  ⚠️  {stn}: 전처리 실패")
            continue

        input_array = np.array([inp], dtype=np.float32)
        result = session.run(None, {"input": input_array})
        pred_normalized = result[0][0]

        data_completeness = min(1.0, len(stn_readings) / WINDOW_SIZE)
        records = []
        for h in range(HORIZON):
            pred_level = denormalize(float(pred_normalized[h]), "water_level", scaler)
            pred_level = max(0.0, pred_level)
            pred_ratio = (pred_level / emb_height) * 100 if emb_height > 0 else 0
            pred_ratio = max(0.0, min(100.0, pred_ratio))
            target_time = (now + timedelta(hours=h + 1)).isoformat()

            records.append({
                "station": stn,
                "river": river,
                "prediction_hour": h + 1,
                "predicted_level": round(pred_level, 2),
                "predicted_ratio": round(pred_ratio, 2),
                "predicted_status": classify_status(pred_ratio),
                "confidence": compute_confidence(h + 1, data_completeness),
                "model_version": model_ver,
                "predicted_at": predicted_at,
                "target_time": target_time,
            })

        saved = sb_insert("flood_predictions", records)
        total_saved += saved

        status_6h = records[5]["predicted_status"] if len(records) > 5 else "?"
        ratio_6h = records[5]["predicted_ratio"] if len(records) > 5 else 0
        emoji = {"danger": "🔴", "warning": "🟡", "safe": "🟢"}.get(status_6h, "⚪")
        print(f"  {emoji} {stn} ({river}): 6h 예측 {ratio_6h:.1f}% [{status_6h}]")
        all_predictions.extend(records)

    print(f"\n💾 Supabase 저장: {total_saved}건")

    danger_count = sum(1 for p in all_predictions if p["predicted_status"] == "danger")
    warning_count = sum(1 for p in all_predictions if p["predicted_status"] == "warning")
    if danger_count:
        print(f"  🔴 위험 예측: {danger_count}건")
    if warning_count:
        print(f"  🟡 주의 예측: {warning_count}건")

    report_health("ok", total_saved)
    print("✅ AI 침수 예측 완료")


if __name__ == "__main__":
    main()

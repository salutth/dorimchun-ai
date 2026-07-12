"""
LSTM 수위 예측 모델 학습 스크립트
- Supabase에서 river_readings + weather_forecasts 이력 추출
- PyTorch LSTM 학습
- ONNX 형식으로 모델 내보내기
- scaler_params.json 저장

사용법: python ml/train_lstm.py
"""

import json
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ML_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from ml.preprocess import (
    FEATURE_NAMES, HORIZON, NUM_FEATURES, WINDOW_SIZE,
    build_feature_row, create_windows, fit_scaler,
    normalize, normalize_row, parse_hour_from_iso, save_scaler,
)


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
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  ⚠️  쿼리 실패 ({table}): {e}")
        return []


def fetch_all_readings():
    """최근 30일간 수위 데이터를 가져온다."""
    print("📥 수위 데이터 조회 중...")
    rows = sb_query(
        "river_readings",
        "select=station,river,water_level,embankment_height,level_ratio,measured_at"
        "&order=measured_at.asc&limit=10000"
    )
    print(f"  → {len(rows)}건 수신")
    return rows


def fetch_all_weather():
    """기상 예보 데이터를 가져온다 (구 스키마: region, precipitation, weather_condition)."""
    import re as _re
    print("📥 기상 예보 조회 중...")
    raw = sb_query(
        "weather_forecasts",
        "select=region,forecast_date,precipitation,weather_condition"
        "&order=forecast_date.asc&limit=10000"
    )
    rows = []
    for w in raw:
        cond = w.get("weather_condition", "")
        hm = _re.search(r'(\d{2}):\d{2}', cond)
        pm = _re.search(r'p(\d+)%', cond)
        rows.append({
            "river": w.get("region", ""),
            "forecast_date": w.get("forecast_date", ""),
            "forecast_hour": f"{int(hm.group(1)):02d}:00" if hm else "00:00",
            "rain_probability": int(pm.group(1)) if pm else 0,
            "rain_amount": str(w.get("precipitation", 0)),
        })
    print(f"  → {len(rows)}건 수신")
    return rows


def group_by_station(readings):
    """관측소별로 시계열 그룹핑."""
    groups = {}
    for r in readings:
        key = r.get("station", "unknown")
        if key not in groups:
            groups[key] = {"river": r.get("river", ""), "readings": []}
        groups[key]["readings"].append(r)
    return groups


def build_weather_map(weather_rows, river):
    """특정 하천의 기상 데이터를 {date: {hour: data}} 형태로."""
    wmap = {}
    for w in weather_rows:
        if w.get("river") != river:
            continue
        date = w.get("forecast_date", "")
        hour_str = w.get("forecast_hour", "00:00")
        try:
            hour = int(hour_str.split(":")[0]) if ":" in str(hour_str) else int(hour_str)
        except (ValueError, TypeError):
            hour = 0
        date_key = f"{date}_{hour}"
        wmap[date_key] = w
    return wmap


def build_station_features(station_readings, weather_rows, river):
    """관측소의 시계열 특성 벡터 리스트를 생성."""
    weather_by_date = {}
    for w in weather_rows:
        if w.get("river") != river:
            continue
        date = w.get("forecast_date", "")
        hour_str = w.get("forecast_hour", "00:00")
        try:
            hour = int(hour_str.split(":")[0]) if ":" in str(hour_str) else int(hour_str)
        except (ValueError, TypeError):
            hour = 0
        if date not in weather_by_date:
            weather_by_date[date] = {}
        weather_by_date[date][hour] = w

    features = []
    for r in station_readings:
        measured = r.get("measured_at", r.get("collected_at", ""))
        hour = parse_hour_from_iso(measured)
        date = measured[:10] if measured else ""
        wmap = weather_by_date.get(date, {})
        feat = build_feature_row(r, wmap, hour)
        features.append(feat)
    return features


def determine_window_horizon(max_seq_len):
    """데이터 양에 따라 윈도우/호라이즌 크기를 적응적으로 결정."""
    if max_seq_len >= WINDOW_SIZE + HORIZON:
        return WINDOW_SIZE, HORIZON
    usable = max_seq_len
    win = max(2, usable * 2 // 3)
    hor = max(1, min(HORIZON, usable - win))
    if win + hor > usable:
        win = max(2, usable - hor)
    return win, hor


def create_windows_adaptive(feature_rows, scaler, win, hor):
    """적응형 윈도우 크기로 학습 데이터를 생성."""
    inputs, targets = [], []
    total = len(feature_rows)
    for i in range(total - win - hor + 1):
        window = feature_rows[i : i + win]
        target_slice = feature_rows[i + win : i + win + hor]
        inp = [normalize_row(r, scaler) for r in window]
        tgt = [normalize(r["water_level"], "water_level", scaler) for r in target_slice]
        inputs.append(inp)
        targets.append(tgt)
    return inputs, targets


def pad_or_trim_window(inp, target_win):
    """윈도우를 표준 크기(WINDOW_SIZE)로 맞춘다. 부족하면 첫 행 복제."""
    if len(inp) >= target_win:
        return inp[-target_win:]
    pad = [inp[0]] * (target_win - len(inp))
    return pad + inp


def pad_or_trim_target(tgt, target_hor):
    """타겟을 표준 크기(HORIZON)로 맞춘다. 부족하면 마지막 값 복제."""
    if len(tgt) >= target_hor:
        return tgt[:target_hor]
    return tgt + [tgt[-1]] * (target_hor - len(tgt))


def train():
    import numpy as np
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    load_env()
    print("=" * 50)
    print("🧠 LSTM 수위 예측 모델 학습")
    print("=" * 50)

    readings = fetch_all_readings()
    weather = fetch_all_weather()

    if len(readings) < 3:
        print(f"❌ 데이터 절대 부족: 최소 3건 필요, {len(readings)}건만 있음")
        sys.exit(1)

    stations = group_by_station(readings)
    print(f"\n📊 관측소 {len(stations)}개 발견")

    all_station_features = []
    max_seq_len = 0
    for stn, info in stations.items():
        feats = build_station_features(info["readings"], weather, info["river"])
        all_station_features.append((stn, feats))
        max_seq_len = max(max_seq_len, len(feats))
        print(f"  📍 {stn}: {len(feats)}시점")

    actual_win, actual_hor = determine_window_horizon(max_seq_len)
    cold_start = actual_win < WINDOW_SIZE or actual_hor < HORIZON
    if cold_start:
        print(f"\n⚡ Cold-start 모드: 윈도우={actual_win}, 호라이즌={actual_hor}")
        print(f"   (표준: 윈도우={WINDOW_SIZE}, 호라이즌={HORIZON})")
        model_version = "v1-coldstart"
    else:
        model_version = "v1"

    all_feature_rows = []
    for stn, feats in all_station_features:
        if len(feats) >= actual_win + actual_hor:
            all_feature_rows.extend(feats)

    if not all_feature_rows:
        print("❌ 학습 가능한 데이터 없음")
        sys.exit(1)

    scaler = fit_scaler(all_feature_rows)
    scaler_path = os.path.join(ML_DIR, "scaler_params.json")
    save_scaler(scaler, scaler_path)
    print(f"\n💾 정규화 파라미터 저장: {scaler_path}")

    all_inputs, all_targets = [], []
    for stn, feats in all_station_features:
        if len(feats) < actual_win + actual_hor:
            continue
        inputs, targets = create_windows_adaptive(feats, scaler, actual_win, actual_hor)
        for inp in inputs:
            all_inputs.append(pad_or_trim_window(inp, WINDOW_SIZE))
        for tgt in targets:
            all_targets.append(pad_or_trim_target(tgt, HORIZON))

    print(f"📦 학습 샘플: {len(all_inputs)}개")

    if len(all_inputs) < 2:
        print("❌ 학습 샘플 부족 (최소 2개 필요)")
        sys.exit(1)

    X = np.array(all_inputs, dtype=np.float32)
    y = np.array(all_targets, dtype=np.float32)

    split = max(1, int(len(X) * 0.8))
    X_train, X_val = X[:split], X[split:] if split < len(X) else X[-1:]
    y_train, y_val = y[:split], y[split:] if split < len(y) else y[-1:]

    print(f"  학습: {len(X_train)}개, 검증: {len(X_val)}개")

    train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
    val_ds = TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val))
    train_dl = DataLoader(train_ds, batch_size=min(32, len(X_train)), shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=min(64, len(X_val)))

    class LSTMPredictor(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm1 = nn.LSTM(NUM_FEATURES, 64, batch_first=True)
            self.drop1 = nn.Dropout(0.2)
            self.lstm2 = nn.LSTM(64, 32, batch_first=True)
            self.drop2 = nn.Dropout(0.2)
            self.fc1 = nn.Linear(32, 32)
            self.relu = nn.ReLU()
            self.fc2 = nn.Linear(32, HORIZON)

        def forward(self, x):
            out, _ = self.lstm1(x)
            out = self.drop1(out)
            out, _ = self.lstm2(out)
            out = self.drop2(out[:, -1, :])
            out = self.relu(self.fc1(out))
            return self.fc2(out)

    model = LSTMPredictor()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.MSELoss()

    epochs = 100 if cold_start else 50
    best_val_loss = float("inf")
    best_state = None
    patience = 15 if cold_start else 10
    no_improve = 0

    print(f"\n🏋️ 학습 시작 (에포크: {epochs}, 조기종료 patience: {patience})")
    for epoch in range(epochs):
        model.train()
        train_loss = 0
        for xb, yb in train_dl:
            pred = model(xb)
            loss = criterion(pred, yb)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(xb)
        train_loss /= len(X_train)

        model.eval()
        val_loss = 0
        with torch.no_grad():
            for xb, yb in val_dl:
                pred = model(xb)
                val_loss += criterion(pred, yb).item() * len(xb)
        val_loss /= len(X_val)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            no_improve = 0
            marker = " ⭐"
        else:
            no_improve += 1
            marker = ""

        if (epoch + 1) % 10 == 0 or marker:
            print(f"  Epoch {epoch+1:3d}/{epochs}  train={train_loss:.6f}  val={val_loss:.6f}{marker}")

        if no_improve >= patience:
            print(f"  ⏹️  조기 종료 (patience {patience})")
            break

    model.load_state_dict(best_state)
    model.eval()
    print(f"\n✅ 최적 검증 손실: {best_val_loss:.6f}")

    if cold_start:
        print(f"⚠️  Cold-start 모델: 데이터 축적 후 재학습 권장 (model_version: {model_version})")

    onnx_path = os.path.join(ML_DIR, "model.onnx")
    dummy = torch.randn(1, WINDOW_SIZE, NUM_FEATURES)
    torch.onnx.export(
        model, dummy, onnx_path,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=14,
    )
    size_kb = os.path.getsize(onnx_path) / 1024
    print(f"💾 ONNX 모델 저장: {onnx_path} ({size_kb:.0f} KB)")

    meta = {"model_version": model_version, "window": actual_win, "horizon": actual_hor, "samples": len(all_inputs)}
    meta_path = os.path.join(ML_DIR, "model_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"💾 모델 메타데이터 저장: {meta_path}")

    print("\n🎉 학습 완료!")


if __name__ == "__main__":
    train()

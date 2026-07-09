"""
LSTM 수위 예측 모델 학습 스크립트 v2
- 앙상블 학습 (3-seed)
- MAE/RMSE/MAPE/상태일치율 검증
- 이상치 탐지 + 선형 보간
- ONNX 내보내기 (앙상블)
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
    DEFAULT_SCALER, FEATURE_NAMES, HORIZON, NUM_FEATURES, WINDOW_SIZE,
    build_feature_row, create_windows, denormalize, detect_outliers,
    fit_scaler, interpolate_gaps, normalize, normalize_row,
    parse_hour_from_iso, parse_weekday_from_iso, save_scaler,
)

ENSEMBLE_SIZE = 3
ENSEMBLE_SEEDS = [42, 123, 7]


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
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  ⚠️  쿼리 실패 ({table}): {e}")
        return []


def fetch_all_readings():
    print("📥 수위 데이터 조회 중...")
    rows = sb_query(
        "river_readings",
        "select=station,river,water_level,embankment_height,level_ratio,measured_at"
        "&order=measured_at.asc&limit=10000"
    )
    print(f"  → {len(rows)}건 수신")
    return rows


def fetch_all_weather():
    print("📥 기상 예보 조회 중...")
    rows = sb_query(
        "weather_forecasts",
        "select=river,forecast_date,forecast_hour,rain_probability,rain_amount"
        "&order=forecast_date.asc&limit=10000"
    )
    print(f"  → {len(rows)}건 수신")
    return rows


def group_by_station(readings):
    groups = {}
    for r in readings:
        key = r.get("station", "unknown")
        if key not in groups:
            groups[key] = {"river": r.get("river", ""), "readings": []}
        groups[key]["readings"].append(r)
    return groups


def build_station_features(station_readings, weather_rows, river):
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

    raw_levels = [r.get("water_level") for r in station_readings]
    outlier_flags = detect_outliers(raw_levels)
    for i, is_outlier in enumerate(outlier_flags):
        if is_outlier:
            raw_levels[i] = None
    interpolated = interpolate_gaps(raw_levels)

    features = []
    level_history = []

    for idx, r in enumerate(station_readings):
        wl = interpolated[idx]
        if wl is None:
            continue

        r_copy = dict(r)
        r_copy["water_level"] = wl
        if r_copy.get("level_ratio") and r.get("water_level") and r["water_level"] > 0:
            r_copy["level_ratio"] = wl / r["water_level"] * r_copy["level_ratio"]

        measured = r.get("measured_at", r.get("collected_at", ""))
        hour = parse_hour_from_iso(measured)
        weekday = parse_weekday_from_iso(measured)
        date = measured[:10] if measured else ""
        wmap = weather_by_date.get(date, {})

        prev_level = level_history[-24] if len(level_history) >= 24 else (level_history[0] if level_history else wl)
        avg_24h = sum(level_history[-24:]) / len(level_history[-24:]) if level_history else wl

        feat = build_feature_row(r_copy, wmap, hour, prev_level, avg_24h, weekday)
        features.append(feat)
        level_history.append(wl)

    return features


def determine_window_horizon(max_seq_len):
    if max_seq_len >= WINDOW_SIZE + HORIZON:
        return WINDOW_SIZE, HORIZON
    usable = max_seq_len
    win = max(2, usable * 2 // 3)
    hor = max(1, min(HORIZON, usable - win))
    if win + hor > usable:
        win = max(2, usable - hor)
    return win, hor


def create_windows_adaptive(feature_rows, scaler, win, hor):
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
    if len(inp) >= target_win:
        return inp[-target_win:]
    pad = [inp[0]] * (target_win - len(inp))
    return pad + inp


def pad_or_trim_target(tgt, target_hor):
    if len(tgt) >= target_hor:
        return tgt[:target_hor]
    return tgt + [tgt[-1]] * (target_hor - len(tgt))


def compute_validation_metrics(model, val_dl, scaler, device="cpu"):
    """MAE, RMSE, MAPE, 상태일치율을 계산."""
    import numpy as np
    import torch

    model.eval()
    all_preds, all_targets = [], []
    with torch.no_grad():
        for xb, yb in val_dl:
            xb = xb.to(device)
            pred = model(xb).cpu().numpy()
            all_preds.append(pred)
            all_targets.append(yb.numpy())

    preds = np.concatenate(all_preds, axis=0)
    targets = np.concatenate(all_targets, axis=0)

    preds_denorm = np.array([
        [denormalize(float(v), "water_level", scaler) for v in row]
        for row in preds
    ])
    targets_denorm = np.array([
        [denormalize(float(v), "water_level", scaler) for v in row]
        for row in targets
    ])

    errors = np.abs(preds_denorm - targets_denorm)
    mae = float(np.mean(errors))
    rmse = float(np.sqrt(np.mean(errors ** 2)))

    nonzero = targets_denorm > 0.1
    if np.any(nonzero):
        mape = float(np.mean(errors[nonzero] / targets_denorm[nonzero]) * 100)
    else:
        mape = 0.0

    def status(level):
        if level >= 80:
            return 2
        if level >= 50:
            return 1
        return 0

    status_match = 0
    total_pts = 0
    for i in range(len(preds_denorm)):
        for j in range(preds_denorm.shape[1]):
            p_status = status(preds_denorm[i][j])
            t_status = status(targets_denorm[i][j])
            if p_status == t_status:
                status_match += 1
            total_pts += 1

    accuracy = status_match / total_pts * 100 if total_pts > 0 else 0

    return {"mae": mae, "rmse": rmse, "mape": mape, "accuracy": accuracy}


def train():
    import numpy as np
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    load_env()
    print("=" * 50)
    print("🧠 LSTM 수위 예측 모델 학습 v2")
    print(f"  앙상블: {ENSEMBLE_SIZE}개 모델, 시드: {ENSEMBLE_SEEDS}")
    print("=" * 50)

    readings = fetch_all_readings()
    weather = fetch_all_weather()

    if len(readings) < 3:
        print(f"❌ 데이터 절대 부족: 최소 3건 필요, {len(readings)}건만 있음")
        sys.exit(1)

    stations = group_by_station(readings)
    print(f"\n📊 관측소 {len(stations)}개 발견")

    rain_count = sum(1 for w in weather if (w.get("rain_probability") or 0) > 0)
    print(f"🌧️ 강우 데이터: {len(weather)}건 중 {rain_count}건에 강수확률 > 0")

    all_station_features = []
    max_seq_len = 0
    for stn, info in stations.items():
        feats = build_station_features(info["readings"], weather, info["river"])
        all_station_features.append((stn, feats))
        max_seq_len = max(max_seq_len, len(feats))
        print(f"  📍 {stn}: {len(feats)}시점 (이상치 제거 후)")

    actual_win, actual_hor = determine_window_horizon(max_seq_len)
    cold_start = actual_win < WINDOW_SIZE or actual_hor < HORIZON
    if cold_start:
        print(f"\n⚡ Cold-start 모드: 윈도우={actual_win}, 호라이즌={actual_hor}")
        model_version = "v2-coldstart"
    else:
        model_version = "v2"

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
    for feat in FEATURE_NAMES:
        s = scaler[feat]
        print(f"  {feat:20s}: [{s['min']:.2f}, {s['max']:.2f}]")

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

    best_ensemble_metrics = None
    ensemble_paths = []

    for eidx, seed in enumerate(ENSEMBLE_SEEDS):
        print(f"\n{'='*40}")
        print(f"🎲 앙상블 모델 {eidx+1}/{ENSEMBLE_SIZE} (seed={seed})")
        print(f"{'='*40}")

        torch.manual_seed(seed)
        np.random.seed(seed)

        model = LSTMPredictor()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        criterion = nn.MSELoss()

        train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
        val_ds = TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val))
        train_dl = DataLoader(train_ds, batch_size=min(32, len(X_train)), shuffle=True)
        val_dl = DataLoader(val_ds, batch_size=min(64, len(X_val)))

        epochs = 100 if cold_start else 50
        best_val_loss = float("inf")
        best_state = None
        patience = 15 if cold_start else 10
        no_improve = 0

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

        metrics = compute_validation_metrics(model, val_dl, scaler)
        print(f"\n  📊 검증 지표:")
        print(f"     MAE:  {metrics['mae']:.2f} cm")
        print(f"     RMSE: {metrics['rmse']:.2f} cm")
        print(f"     MAPE: {metrics['mape']:.1f}%")
        print(f"     상태일치율: {metrics['accuracy']:.1f}%")

        onnx_path = os.path.join(ML_DIR, f"model_ensemble_{eidx}.onnx")
        dummy = torch.randn(1, WINDOW_SIZE, NUM_FEATURES)
        torch.onnx.export(
            model, dummy, onnx_path,
            input_names=["input"], output_names=["output"],
            dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
            opset_version=14,
        )
        ensemble_paths.append(onnx_path)

        if best_ensemble_metrics is None or metrics["mape"] < best_ensemble_metrics["mape"]:
            best_ensemble_metrics = metrics
            best_onnx_path = onnx_path

    import shutil
    main_model_path = os.path.join(ML_DIR, "model.onnx")
    shutil.copy2(best_onnx_path, main_model_path)
    print(f"\n💾 최적 모델 → model.onnx 복사")

    meta = {
        "model_version": model_version,
        "window": actual_win,
        "horizon": actual_hor,
        "samples": len(all_inputs),
        "num_features": NUM_FEATURES,
        "feature_names": FEATURE_NAMES,
        "ensemble_size": ENSEMBLE_SIZE,
        "ensemble_seeds": ENSEMBLE_SEEDS,
        "validation_metrics": best_ensemble_metrics,
        "weather_data_count": len(weather),
        "rain_data_available": rain_count > 0,
    }
    meta_path = os.path.join(ML_DIR, "model_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"🎉 앙상블 학습 완료!")
    print(f"  모델 버전: {model_version}")
    print(f"  앙상블: {ENSEMBLE_SIZE}개 모델")
    print(f"  최적 MAPE: {best_ensemble_metrics['mape']:.1f}%")
    print(f"  최적 상태일치율: {best_ensemble_metrics['accuracy']:.1f}%")
    print(f"{'='*50}")


if __name__ == "__main__":
    train()

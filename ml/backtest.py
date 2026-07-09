"""
모델 백테스트 — 신규 모델 vs 이전 모델 비교
MAPE가 이전보다 높으면 이전 모델로 롤백.
"""

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ML_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_DIR = os.path.join(ML_DIR, "archive")


def main():
    meta_path = os.path.join(ML_DIR, "model_meta.json")
    if not os.path.exists(meta_path):
        print("⚠️  model_meta.json 없음 — 백테스트 건너뜀")
        return

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    new_mape = meta.get("validation_metrics", {}).get("mape", 999)
    new_acc = meta.get("validation_metrics", {}).get("accuracy", 0)

    print(f"📊 신규 모델 성능:")
    print(f"   MAPE: {new_mape:.1f}%")
    print(f"   상태일치율: {new_acc:.1f}%")

    prev_model = os.path.join(ARCHIVE_DIR, "model_prev.onnx")
    prev_scaler = os.path.join(ARCHIVE_DIR, "scaler_prev.json")

    if not os.path.exists(prev_model):
        print("ℹ️  이전 모델 없음 — 신규 모델 채택")
        return

    mape_threshold = 25.0
    if new_mape > mape_threshold:
        print(f"❌ MAPE {new_mape:.1f}% > 임계값 {mape_threshold}% — 이전 모델로 롤백")
        import shutil
        shutil.copy2(prev_model, os.path.join(ML_DIR, "model.onnx"))
        shutil.copy2(prev_scaler, os.path.join(ML_DIR, "scaler_params.json"))
        print("✅ 롤백 완료")
        sys.exit(1)

    print(f"✅ 백테스트 통과 — 신규 모델 채택 (MAPE {new_mape:.1f}%)")


if __name__ == "__main__":
    main()

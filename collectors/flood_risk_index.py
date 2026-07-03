"""
K-SAFE 홍수위험지수 — 다중소스 종합 위험도 산출 (Phase 3-2)

K-SAFE 4D Agentic AI 프레임워크를 하천 방재에 적용:
  W1 Water-Level    현재 수위비율 기반 위험도
  W2 Weather-Sensor 기상예보 강수확률·강수량 기반 위험도
  W3 AI-Predictor   LSTM 예측 트렌드 기반 위험도
  W4 History-Analyzer 최근 수위 변동 패턴 기반 위험도
  V1 Cross-Validator 규칙기반 vs AI 교차검증 신뢰도

4-Stage 재난관리 단계 (NGA 1979 + Sendai 2015):
  prevention  예방 — 정상 범위, 모니터링 단계
  preparedness 대비 — 주의 신호 감지, 선제 대응 준비
  response    대응 — 위험 수준, 즉각 조치 필요
  recovery    복구 — 위험 후 안정화 단계

4R Resilience (Bruneau et al. 2003):
  robustness    견고성 — 제방 여유고 기반
  redundancy    중복성 — 데이터 소스 다중성
  resourcefulness 동원성 — 예보 시스템 가용 여부
  rapidity      신속성 — 데이터 수집 최신성

Bounded Autonomy: AI는 위험도를 제안만 하고, 최종 판단은 인간 검토자가 내린다.
"""

import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KST = timezone(timedelta(hours=9))


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
    conflict = ""
    if table == "flood_risk_index":
        conflict = "?on_conflict=station,calculated_at"
    body = json.dumps(records, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{sb_url}/rest/v1/{table}{conflict}",
        data=body,
        headers={
            "apikey": sb_key,
            "Authorization": f"Bearer {sb_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal,resolution=merge-duplicates",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return len(records) if resp.status in (200, 201) else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# W1: Water-Level Agent — 현재 수위비율 기반 위험도
# ---------------------------------------------------------------------------
def score_water_level(level_ratio):
    if level_ratio is None:
        return 0.0
    ratio = float(level_ratio)
    if ratio >= 80:
        return min(100.0, 60 + (ratio - 80) * 2)
    if ratio >= 50:
        return 30 + (ratio - 50) * (30 / 30)
    if ratio >= 30:
        return 10 + (ratio - 30) * (20 / 20)
    return max(0, ratio / 30 * 10)


# ---------------------------------------------------------------------------
# W2: Weather-Sensor Agent — 기상예보 기반 위험도
# ---------------------------------------------------------------------------
def score_weather(rain_prob, rain_amount):
    prob = float(rain_prob or 0)
    amount = float(rain_amount or 0)
    prob_score = prob * 0.4
    if amount >= 80:
        amt_score = 60
    elif amount >= 30:
        amt_score = 30 + (amount - 30) * (30 / 50)
    elif amount >= 10:
        amt_score = 10 + (amount - 10) * (20 / 20)
    else:
        amt_score = amount
    return min(100.0, prob_score + amt_score)


# ---------------------------------------------------------------------------
# W3: AI-Predictor Agent — LSTM 예측 트렌드 기반 위험도
# ---------------------------------------------------------------------------
def score_prediction(predictions):
    if not predictions:
        return 0.0
    max_ratio = max(float(p.get("predicted_ratio", 0)) for p in predictions)
    trend_scores = []
    for p in predictions:
        ratio = float(p.get("predicted_ratio", 0))
        confidence = float(p.get("confidence", 0.5))
        if ratio >= 80:
            s = 80 + (ratio - 80)
        elif ratio >= 50:
            s = 40 + (ratio - 50) * (40 / 30)
        else:
            s = ratio * (40 / 50)
        trend_scores.append(s * confidence)
    avg_score = sum(trend_scores) / len(trend_scores) if trend_scores else 0
    return min(100.0, max(avg_score, max_ratio * 0.8))


# ---------------------------------------------------------------------------
# W4: History-Analyzer Agent — 최근 수위 변동 패턴
# ---------------------------------------------------------------------------
def score_history(readings):
    if len(readings) < 3:
        return 0.0
    levels = [float(r.get("level_ratio", 0)) for r in readings]
    current = levels[-1]
    avg_prev = sum(levels[:-1]) / len(levels[:-1])
    change_rate = current - avg_prev

    if change_rate > 20:
        trend_score = 80
    elif change_rate > 10:
        trend_score = 50 + (change_rate - 10) * 3
    elif change_rate > 5:
        trend_score = 30 + (change_rate - 5) * 4
    elif change_rate > 0:
        trend_score = change_rate * 6
    else:
        trend_score = max(0, 10 + change_rate * 2)

    volatility = 0
    for i in range(1, len(levels)):
        volatility += abs(levels[i] - levels[i - 1])
    volatility /= len(levels) - 1

    vol_score = min(30, volatility * 3)
    return min(100.0, trend_score + vol_score)


# ---------------------------------------------------------------------------
# V1: Cross-Validator — 규칙기반 vs AI 교차검증 신뢰도
# ---------------------------------------------------------------------------
def cross_validate(w1_score, w3_score):
    if w3_score == 0:
        return 0.5
    diff = abs(w1_score - w3_score)
    if diff < 10:
        return 1.0
    if diff < 20:
        return 0.85
    if diff < 30:
        return 0.7
    return max(0.3, 1.0 - diff / 100)


# ---------------------------------------------------------------------------
# 4-Stage 재난관리 단계 분류
# ---------------------------------------------------------------------------
def classify_stage(composite_score, trend_direction):
    if composite_score >= 70:
        return "response"
    if composite_score >= 40:
        return "preparedness"
    if trend_direction == "falling" and composite_score < 30:
        return "recovery"
    return "prevention"


def get_trend_direction(readings):
    if len(readings) < 3:
        return "stable"
    recent = [float(r.get("level_ratio", 0)) for r in readings[-3:]]
    if recent[-1] > recent[0] + 3:
        return "rising"
    if recent[-1] < recent[0] - 3:
        return "falling"
    return "stable"


# ---------------------------------------------------------------------------
# 4R Resilience 점수 계산
# ---------------------------------------------------------------------------
def compute_resilience(station_data, data_sources_count, data_age_minutes):
    emb = float(station_data.get("embankment_height", 0) or 0)
    level = float(station_data.get("water_level", 0) or 0)

    if emb > 0 and level > 0:
        margin = (emb - level) / emb * 100
        robustness = min(100, max(0, margin * 1.5))
    else:
        robustness = 50

    redundancy = min(100, data_sources_count * 25)

    resourcefulness = 100 if data_sources_count >= 3 else data_sources_count * 33

    if data_age_minutes <= 15:
        rapidity = 100
    elif data_age_minutes <= 60:
        rapidity = 80
    elif data_age_minutes <= 180:
        rapidity = 50
    else:
        rapidity = max(10, 100 - data_age_minutes / 10)

    return {
        "robustness": round(robustness, 1),
        "redundancy": round(redundancy, 1),
        "resourcefulness": round(resourcefulness, 1),
        "rapidity": round(rapidity, 1),
        "average": round((robustness + redundancy + resourcefulness + rapidity) / 4, 1),
    }


# ---------------------------------------------------------------------------
# 종합 K-SAFE Flood Risk Index
# ---------------------------------------------------------------------------
WEIGHTS = {"w1": 0.35, "w2": 0.25, "w3": 0.25, "w4": 0.15}


def compute_composite(w1, w2, w3, w4, cv):
    raw = (
        w1 * WEIGHTS["w1"]
        + w2 * WEIGHTS["w2"]
        + w3 * WEIGHTS["w3"]
        + w4 * WEIGHTS["w4"]
    )
    return round(min(100.0, raw * cv), 1)


def risk_grade(score):
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "moderate"
    if score >= 20:
        return "low"
    return "minimal"


def main():
    print("=" * 50)
    print("🛡️  K-SAFE 홍수위험지수 산출")
    print("=" * 50)

    load_env()
    now = datetime.now(KST)

    print("\n📥 데이터 수집 중...")
    readings = sb_query(
        "river_readings",
        "select=station,river,water_level,embankment_height,level_ratio,status,measured_at"
        "&order=measured_at.desc&limit=500",
    )
    print(f"  수위: {len(readings)}건")

    today = now.strftime("%Y-%m-%d")
    weather = sb_query(
        "weather_forecasts",
        f"select=river,forecast_hour,rain_probability,rain_amount"
        f"&forecast_date=eq.{today}&limit=500",
    )
    print(f"  기상: {len(weather)}건")

    predictions = sb_query(
        "flood_predictions",
        "select=station,river,prediction_hour,predicted_ratio,predicted_status,confidence,predicted_at"
        "&order=predicted_at.desc&limit=300",
    )
    print(f"  AI예측: {len(predictions)}건")

    stations = {}
    for r in readings:
        stn = r.get("station", "unknown")
        if stn not in stations:
            stations[stn] = {
                "river": r.get("river", ""),
                "latest": r,
                "readings": [],
            }
        stations[stn]["readings"].append(r)

    for info in stations.values():
        info["readings"].sort(key=lambda x: x.get("measured_at", ""))

    weather_by_river = {}
    for w in weather:
        river = w.get("river", "")
        if river not in weather_by_river:
            weather_by_river[river] = []
        weather_by_river[river].append(w)

    pred_by_station = {}
    for p in predictions:
        stn = p.get("station", "")
        if stn not in pred_by_station:
            pred_by_station[stn] = []
        pred_by_station[stn].append(p)

    records = []
    print(f"\n🛡️  {len(stations)}개 관측소 위험지수 산출...")

    for stn, info in stations.items():
        river = info["river"]
        latest = info["latest"]
        stn_readings = info["readings"]

        w1 = score_water_level(latest.get("level_ratio"))

        river_weather = weather_by_river.get(river, [])
        if river_weather:
            max_prob = max(float(w.get("rain_probability", 0)) for w in river_weather)
            max_amount = max(float(w.get("rain_amount", 0)) for w in river_weather)
            w2 = score_weather(max_prob, max_amount)
        else:
            w2 = 0.0

        stn_preds = pred_by_station.get(stn, [])
        w3 = score_prediction(stn_preds)

        w4 = score_history(stn_readings)

        cv = cross_validate(w1, w3)

        composite = compute_composite(w1, w2, w3, w4, cv)
        grade = risk_grade(composite)

        data_sources = 1
        if river_weather:
            data_sources += 1
        if stn_preds:
            data_sources += 1
        if len(stn_readings) >= 3:
            data_sources += 1

        measured_at = latest.get("measured_at", "")
        if measured_at:
            try:
                mt = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
                age_minutes = (now - mt).total_seconds() / 60
            except (ValueError, TypeError):
                age_minutes = 60
        else:
            age_minutes = 60

        resilience = compute_resilience(latest, data_sources, age_minutes)

        trend = get_trend_direction(stn_readings)
        stage = classify_stage(composite, trend)

        record = {
            "station": stn,
            "river": river,
            "composite_score": composite,
            "risk_grade": grade,
            "w1_water_level": round(w1, 1),
            "w2_weather": round(w2, 1),
            "w3_prediction": round(w3, 1),
            "w4_history": round(w4, 1),
            "cross_validation": round(cv, 2),
            "disaster_stage": stage,
            "trend_direction": trend,
            "resilience_robustness": resilience["robustness"],
            "resilience_redundancy": resilience["redundancy"],
            "resilience_resourcefulness": resilience["resourcefulness"],
            "resilience_rapidity": resilience["rapidity"],
            "resilience_average": resilience["average"],
            "data_sources": data_sources,
            "calculated_at": now.isoformat(),
        }
        records.append(record)

        stage_emoji = {
            "prevention": "🟢", "preparedness": "🟡",
            "response": "🔴", "recovery": "🔵",
        }
        grade_label = {
            "critical": "🔴 심각 Critical", "high": "🟠 높음 High",
            "moderate": "🟡 보통 Moderate", "low": "🟢 낮음 Low",
            "minimal": "⚪ 최소 Minimal",
        }
        print(
            f"  {grade_label.get(grade, '⚪')} {stn} ({river}): "
            f"지수={composite} "
            f"단계={stage_emoji.get(stage, '⚪')}{stage} "
            f"W1={w1:.0f} W2={w2:.0f} W3={w3:.0f} W4={w4:.0f} "
            f"4R={resilience['average']:.0f}"
        )

    saved = sb_insert("flood_risk_index", records)
    print(f"\n💾 Supabase 저장: {saved}건")

    critical = sum(1 for r in records if r["risk_grade"] == "critical")
    high = sum(1 for r in records if r["risk_grade"] == "high")
    if critical:
        print(f"  🔴 심각: {critical}개소 — 즉각 조치 검토 필요 (Bounded Autonomy)")
    if high:
        print(f"  🟠 높음: {high}개소 — 주의 관찰 권고")

    sb_insert("collector_health", [{
        "collector": "flood_risk_index",
        "status": "ok",
        "record_count": saved,
        "collected_at": now.isoformat(),
    }])

    print("✅ K-SAFE 홍수위험지수 산출 완료")


if __name__ == "__main__":
    main()

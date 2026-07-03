"""
기상 예보 수집기 — 하천ON Phase 1-2
- 입력: Open-Meteo API (무료, API 키 불필요)
- 처리: 21개 하천 위치 기반 48시간 강수·기온 예보 수집
- 출력: Supabase weather_forecasts 테이블 저장 + 침수 위험 경보
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RIVER_LOCATIONS = {
    "도림천": {"lat": 37.4838, "lng": 126.9295},
    "안양천": {"lat": 37.4750, "lng": 126.8870},
    "중랑천": {"lat": 37.5950, "lng": 127.0500},
    "탄천": {"lat": 37.5000, "lng": 127.0700},
    "불광천": {"lat": 37.5850, "lng": 126.9150},
    "홍제천": {"lat": 37.5750, "lng": 126.9350},
    "방학천": {"lat": 37.6540, "lng": 127.0250},
    "우이천": {"lat": 37.6450, "lng": 127.0130},
    "정릉천": {"lat": 37.5950, "lng": 127.0050},
    "청계천": {"lat": 37.5700, "lng": 127.0000},
    "양재천": {"lat": 37.4720, "lng": 127.0400},
    "성북천": {"lat": 37.5920, "lng": 127.0020},
    "묵동천": {"lat": 37.6150, "lng": 127.0780},
    "전농천": {"lat": 37.5780, "lng": 127.0560},
    "월계천": {"lat": 37.6280, "lng": 127.0580},
    "반포천": {"lat": 37.5050, "lng": 126.9950},
    "여의천": {"lat": 37.5250, "lng": 126.9230},
    "봉원천": {"lat": 37.5650, "lng": 126.9530},
    "녹번천": {"lat": 37.6050, "lng": 126.9280},
    "세곡천": {"lat": 37.4650, "lng": 127.0850},
    "내부천": {"lat": 37.4850, "lng": 126.9680},
}

WMO_CODES = {
    0: "맑음", 1: "대체로맑음", 2: "구름조금", 3: "흐림",
    45: "안개", 48: "안개", 51: "이슬비", 53: "이슬비", 55: "이슬비",
    61: "비", 63: "비", 65: "폭우",
    71: "눈", 73: "눈", 75: "폭설",
    80: "소나기", 81: "소나기", 82: "폭우",
    95: "뇌우", 96: "우박뇌우", 99: "우박뇌우",
}


def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()


def fetch_weather(lat, lng):
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}"
        f"&hourly=temperature_2m,precipitation_probability,precipitation,"
        f"weathercode,relativehumidity_2m,windspeed_10m"
        f"&timezone=Asia/Seoul&forecast_days=2"
    )
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None


def parse_weather(data, river):
    records = []
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    rain_probs = hourly.get("precipitation_probability", [])
    precips = hourly.get("precipitation", [])
    codes = hourly.get("weathercode", [])
    humids = hourly.get("relativehumidity_2m", [])
    winds = hourly.get("windspeed_10m", [])

    for i in range(len(times)):
        t = times[i]
        date_part = t[:10]
        hour_part = t[11:16]
        code = codes[i] if i < len(codes) else 0
        sky = WMO_CODES.get(code, str(code))
        precip = precips[i] if i < len(precips) else 0

        rain_prob = rain_probs[i] if i < len(rain_probs) else 0
        records.append({
            "region": river,
            "forecast_date": date_part,
            "temperature": temps[i] if i < len(temps) else None,
            "precipitation": precip,
            "humidity": humids[i] if i < len(humids) else None,
            "wind_speed": winds[i] if i < len(winds) else None,
            "weather_condition": f"{sky} {hour_part} p{int(rain_prob)}%",
            "collected_at": datetime.now().isoformat(),
            "_rain_probability": rain_prob,
            "_forecast_hour": hour_part,
            "_sky_status": sky,
        })

    return records


def save_to_supabase(records):
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_KEY")

    if not sb_url or not sb_key:
        print("  ⚠️  Supabase 환경변수 없음 — 저장 건너뜀")
        return 0

    batch_size = 100
    saved = 0
    for i in range(0, len(records), batch_size):
        batch = [{k: v for k, v in r.items() if not k.startswith("_")} for r in records[i : i + batch_size]]
        body = json.dumps(batch, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{sb_url}/rest/v1/weather_forecasts",
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
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201):
                    saved += len(batch)
        except Exception as e:
            print(f"  ⚠️  배치 저장 실패: {e}")

    return saved


def main():
    load_env()

    print("=" * 60)
    print("  기상 예보 수집기 — 하천ON Phase 1-2")
    print(f"  수집 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("  데이터 소스: Open-Meteo (48시간 예보)")
    print("=" * 60)
    print()

    all_records = []
    rain_alerts = []

    for river, coord in RIVER_LOCATIONS.items():
        data = fetch_weather(coord["lat"], coord["lng"])
        if not data:
            print(f"  {river:8s}  ❌ 수집 실패")
            continue

        records = parse_weather(data, river)
        if not records:
            print(f"  {river:8s}  ❌ 파싱 실패")
            continue

        max_rain_prob = max(r["_rain_probability"] for r in records)
        max_precip = max(r["precipitation"] for r in records)
        rain_hours = [r for r in records if r["_rain_probability"] >= 60]

        status = "🟢"
        if max_rain_prob >= 80 or max_precip >= 10:
            status = "🔴"
        elif max_rain_prob >= 60 or max_precip >= 5:
            status = "🟡"

        print(f"  {river:8s}  {status} 강수확률 최대 {max_rain_prob:3d}%  강수량 최대 {max_precip:5.1f}mm  예보 {len(records)}건")

        for r in rain_hours:
            rain_alerts.append({
                "river": river,
                "date": r["forecast_date"],
                "hour": r["_forecast_hour"],
                "prob": r["_rain_probability"],
                "precip": r["precipitation"],
                "sky": r["_sky_status"],
            })

        all_records.extend(records)

    print()
    print(f"  === 수집 요약 ===")
    print(f"  총 예보 데이터: {len(all_records)}건 (21개 하천 × 48시간)")

    if rain_alerts:
        print()
        print(f"  ⚠️  강수 경보 ({len(rain_alerts)}건) — 문화재 침수 주의!")
        print(f"  {'하천':8s}  {'날짜':12s}  {'시간':6s}  {'확률':5s}  {'강수량':7s}  {'상태'}")
        print(f"  {'-'*60}")
        shown = sorted(rain_alerts, key=lambda x: (-x["prob"], x["date"], x["hour"]))[:20]
        for a in shown:
            print(f"  {a['river']:8s}  {a['date']:12s}  {a['hour']:6s}  {int(a['prob']):3d}%   {a['precip']:5.1f}mm  {a['sky']}")
        if len(rain_alerts) > 20:
            print(f"  ... 외 {len(rain_alerts) - 20}건")
    else:
        print()
        print("  ✅ 강수 예보 없음 — 문화재 침수 위험 낮음")

    print()
    saved = save_to_supabase(all_records)
    if saved:
        print(f"  💾 Supabase 저장 완료: {saved}건")
    print()


if __name__ == "__main__":
    main()

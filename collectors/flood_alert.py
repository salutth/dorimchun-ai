"""
침수 위험 경보 시스템 — 하천ON Phase 3
- 입력: Supabase 수위 데이터 + 기상 예보 + 문화재 위치
- 처리: 위험도 판정 → 3단계 경보 생성
- 출력: 텔레그램 봇 알림 + Supabase alert_history 저장

경보 기준:
  🔴 긴급: 수위비율 80%↑ AND 문화재 1km 이내
  🟡 주의: 수위비율 60%↑ OR 강수확률 80%↑ (문화재 1.5km 이내)
  🟢 안전: 그 외
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    conflict = ""
    if table == "flood_alerts":
        conflict = "?on_conflict=station,issued_at"
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


def send_telegram(token, chat_id, message):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  ⚠️  텔레그램 전송 실패: {e}")
        return False


def assess_flood_risk(readings, weather_by_river, assets_by_river):
    """수위 + 강수 + 문화재 기반 침수 위험도 판정"""
    alerts = []
    now_hour = datetime.now().hour

    station_map = {}
    for r in readings:
        if r["station"] not in station_map:
            station_map[r["station"]] = r

    for station, r in station_map.items():
        river = (r.get("river") or "").strip()
        ratio = r.get("level_ratio") or 0
        water_level = r.get("water_level") or 0
        embankment = r.get("embankment_height") or 0

        weather = weather_by_river.get(river, [])
        future_weather = [w for w in weather if int(w.get("forecast_hour", "0")[:2]) >= now_hour]
        max_rain_prob = max((w.get("rain_probability", 0) for w in future_weather), default=0)
        max_precip = max((float(w.get("rain_amount", "0")) for w in future_weather), default=0)

        nearby_assets = assets_by_river.get(river, [])
        high_grade_assets = [
            a for a in nearby_assets
            if a.get("grade") in ("국보", "보물", "사적", "천연기념물")
            and (a.get("distance_km") or 99) <= 1.0
        ]
        close_assets = [a for a in nearby_assets if (a.get("distance_km") or 99) <= 1.5]

        level = "safe"
        reason = []

        if ratio >= 80 and high_grade_assets:
            level = "critical"
            reason.append(f"수위비율 {ratio:.1f}% (위험)")
            reason.append(f"국보·보물·사적 {len(high_grade_assets)}건 1km 이내")
        elif ratio >= 80:
            level = "danger"
            reason.append(f"수위비율 {ratio:.1f}% (위험)")
        elif ratio >= 60 and max_rain_prob >= 70:
            level = "danger"
            reason.append(f"수위비율 {ratio:.1f}% + 강수확률 {max_rain_prob}%")
            if high_grade_assets:
                reason.append(f"문화재 {len(high_grade_assets)}건 위험")
        elif ratio >= 60:
            level = "warning"
            reason.append(f"수위비율 {ratio:.1f}% (주의)")
        elif max_rain_prob >= 80:
            level = "warning"
            reason.append(f"강수확률 {max_rain_prob}% (호우 예상)")

        if level != "safe":
            alerts.append({
                "station": station,
                "river": river,
                "gu": r.get("gu", ""),
                "level": level,
                "ratio": ratio,
                "water_level": water_level,
                "embankment": embankment,
                "rain_prob": max_rain_prob,
                "rain_amount": max_precip,
                "nearby_assets_count": len(close_assets),
                "high_grade_count": len(high_grade_assets),
                "high_grade_names": [a["name"] for a in high_grade_assets[:3]],
                "reasons": reason,
            })

    return sorted(alerts, key=lambda x: {"critical": 0, "danger": 1, "warning": 2}.get(x["level"], 3))


def format_telegram_message(alerts):
    if not alerts:
        return None

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    critical = [a for a in alerts if a["level"] == "critical"]
    danger = [a for a in alerts if a["level"] == "danger"]
    warning = [a for a in alerts if a["level"] == "warning"]

    lines = [f"🚨 <b>하천ON 침수 위험 경보</b>", f"⏰ {now}", ""]

    if critical:
        lines.append("🔴 <b>긴급 — 문화재 침수 위험</b>")
        for a in critical:
            lines.append(f"  📍 {a['station']} ({a['river']}, {a['gu']})")
            lines.append(f"     수위 {a['ratio']:.1f}% | 강수 {a['rain_prob']}%")
            if a["high_grade_names"]:
                lines.append(f"     ⚠️ {', '.join(a['high_grade_names'])}")
        lines.append("")

    if danger:
        lines.append("🟠 <b>위험</b>")
        for a in danger:
            lines.append(f"  📍 {a['station']} ({a['river']})")
            lines.append(f"     {' | '.join(a['reasons'])}")
        lines.append("")

    if warning:
        lines.append("🟡 <b>주의</b>")
        for a in warning:
            lines.append(f"  📍 {a['station']} ({a['river']}) — {a['reasons'][0]}")
        lines.append("")

    lines.append(f"📊 상세: https://dorimchun-ai.pages.dev/river-on")
    lines.append(f"💧 대시보드: https://dorimchun-ai.pages.dev/dashboard")

    return "\n".join(lines)


def main():
    load_env()

    print("=" * 60)
    print("  침수 위험 경보 시스템 — 하천ON Phase 3")
    print(f"  점검 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print()

    print("  📡 데이터 수집 중...")
    readings = sb_query("river_readings", "select=*&order=measured_at.desc&limit=50")
    today = datetime.now().strftime("%Y-%m-%d")
    weather_raw = sb_query(
        "weather_forecasts",
        f"select=region,precipitation,weather_condition"
        f"&forecast_date=eq.{today}&limit=500"
    )
    weather = []
    for w in weather_raw:
        wc = w.get("weather_condition", "")
        parts = wc.rsplit(" p", 1)
        hour = ""
        rain_prob = 0
        if len(parts) >= 2:
            try:
                rain_prob = int(parts[1].replace("%", ""))
            except ValueError:
                pass
            sky_parts = parts[0].rsplit(" ", 1)
            if len(sky_parts) == 2:
                hour = sky_parts[1]
        weather.append({
            "river": w.get("region", ""),
            "forecast_hour": hour,
            "rain_probability": rain_prob,
            "rain_amount": str(w.get("precipitation", 0)),
            "sky_status": parts[0] if parts else "",
        })
    assets_raw = sb_query(
        "cultural_assets",
        "select=name,category,river,description&limit=500"
    )
    assets = []
    for a in assets_raw:
        dist = 99.0
        desc = a.get("description", "") or ""
        if "거리:" in desc:
            try:
                dist = float(desc.split("거리:")[1].split("km")[0])
            except (ValueError, IndexError):
                pass
        assets.append({
            "name": a.get("name", ""),
            "grade": a.get("category", ""),
            "nearest_river": a.get("river", ""),
            "distance_km": dist,
        })

    print(f"  수위: {len(readings)}건 | 기상: {len(weather)}건 | 문화재: {len(assets)}건")
    print()

    weather_by_river = {}
    for w in weather:
        r = w.get("river", "")
        if r not in weather_by_river:
            weather_by_river[r] = []
        weather_by_river[r].append(w)

    assets_by_river = {}
    for a in assets:
        r = a.get("nearest_river", "") or a.get("river", "")
        if r not in assets_by_river:
            assets_by_river[r] = []
        assets_by_river[r].append(a)

    print("  🔍 침수 위험도 판정 중...")
    alerts = assess_flood_risk(readings, weather_by_river, assets_by_river)

    critical = [a for a in alerts if a["level"] == "critical"]
    danger = [a for a in alerts if a["level"] == "danger"]
    warning = [a for a in alerts if a["level"] == "warning"]

    print()
    if not alerts:
        print("  ✅ 현재 침수 위험 없음 — 모든 하천 안전")
    else:
        print(f"  경보 현황: 긴급 {len(critical)}건 | 위험 {len(danger)}건 | 주의 {len(warning)}건")
        print()
        for a in alerts:
            icon = {"critical": "🔴", "danger": "🟠", "warning": "🟡"}[a["level"]]
            label = {"critical": "긴급", "danger": "위험", "warning": "주의"}[a["level"]]
            print(f"  {icon} [{label}] {a['station']} ({a['river']}, {a['gu']})")
            print(f"     수위 {a['ratio']:.1f}% | 강수확률 {a['rain_prob']}% | 인근 문화재 {a['nearby_assets_count']}건")
            for reason in a["reasons"]:
                print(f"     → {reason}")
            if a["high_grade_names"]:
                print(f"     ⚠️  위험 문화재: {', '.join(a['high_grade_names'])}")

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")

    if alerts:
        message = format_telegram_message(alerts)
        if tg_token and tg_chat:
            print()
            print("  📤 텔레그램 경보 전송 중...")
            if send_telegram(tg_token, tg_chat, message):
                print("  ✅ 텔레그램 전송 완료")
            else:
                print("  ❌ 텔레그램 전송 실패")
        else:
            print()
            print("  ℹ️  텔레그램 미설정 — .env에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 추가 필요")
            print()
            print("  --- 경보 메시지 미리보기 ---")
            print(message.replace("<b>", "").replace("</b>", ""))

        alert_records = []
        for a in alerts:
            reasons_str = " | ".join(a["reasons"])
            asset_info = ""
            if a["high_grade_names"]:
                asset_info = f" 문화재: {', '.join(a['high_grade_names'])}"
            alert_records.append({
                "river": a["river"],
                "station": a["station"],
                "alert_level": a["level"],
                "water_level": a["water_level"],
                "threshold": a["embankment"],
                "message": f"[{a['gu']}] {reasons_str}{asset_info}",
                "issued_at": datetime.now().isoformat(),
            })
        saved = sb_insert("flood_alerts", alert_records)
        if saved:
            print(f"\n  💾 경보 이력 저장: {saved}건")

    print()


if __name__ == "__main__":
    main()

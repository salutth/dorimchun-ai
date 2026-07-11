"""
한강 본류 수위 모니터링 + Supabase 저장
- 입력: 한강홍수통제소 Open API (hrfco.go.kr)
- 처리: 서울 구간 한강 관측소 수위 데이터 수집 + river_readings 형식 변환
- 출력: Supabase river_readings 테이블 저장 (river='한강')

API: https://api.hrfco.go.kr/{HRFCO_API_KEY}/waterlevel/list/10M.json
인증키 발급: https://www.hrfco.go.kr/web/openapiPage/certifyKey.do
"""

import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HANGANG_STATIONS = {
    "1018640": {"name": "광나루", "gu": "강동구", "pfh": 13.0},
    "1018655": {"name": "뚝섬", "gu": "성동구", "pfh": 8.5},
    "1018658": {"name": "뚝섬(잠실)", "gu": "성동구", "pfh": 13.5},
    "1018662": {"name": "한강대교", "gu": "용산구", "pfh": 15.5},
    "1018669": {"name": "창천(여의)", "gu": "영등포구", "pfh": 7.9},
    "1018670": {"name": "행주대교", "gu": "강서구", "pfh": 6.2},
    "1018675": {"name": "중랑교", "gu": "성동구", "pfh": 7.9},
    "1018680": {"name": "노량진", "gu": "동작구", "pfh": 15.6},
    "1018683": {"name": "잠수교", "gu": "서초구", "pfh": 13.3},
    "1018695": {"name": "초부대교", "gu": "마포구", "pfh": 4.9},
    "1018697": {"name": "영등포", "gu": "영등포구", "pfh": 11.0},
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


def fetch_all_waterlevel(api_key):
    url = f"https://api.hrfco.go.kr/{api_key}/waterlevel/list/10M.json"
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "RiverWatch/2.3")
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_station_info(api_key):
    url = f"https://api.hrfco.go.kr/{api_key}/waterlevel/info.json"
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "RiverWatch/2.3")
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {s["wlobscd"]: s for s in data.get("content", [])}


def water_level_status(wl_m, pfh_m):
    try:
        wl = float(wl_m)
        pfh = float(pfh_m)
        if pfh <= 0:
            return "unknown", 0
        ratio = (wl / pfh) * 100
        if ratio >= 80:
            return "danger", ratio
        elif ratio >= 50:
            return "warning", ratio
        else:
            return "safe", ratio
    except (ValueError, ZeroDivisionError, TypeError):
        return "unknown", 0


def save_to_supabase(records):
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not sb_url or not sb_key:
        print("  [Supabase] URL/KEY 없음 — 저장 건너뜀")
        return 0

    url = f"{sb_url}/rest/v1/river_readings?on_conflict=station,measured_at"
    payload = json.dumps(records, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("apikey", sb_key)
    req.add_header("Authorization", f"Bearer {sb_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=minimal,resolution=merge-duplicates")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                return len(records)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [Supabase] 저장 실패 ({e.code}): {body}")
    except Exception as e:
        print(f"  [Supabase] 연결 실패: {e}")
    return 0


def report_health(status, record_count=0, error_message=None):
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not sb_url or not sb_key:
        return

    record = {
        "collector": "hangang_monitor",
        "status": status,
        "record_count": record_count,
        "error_message": error_message,
    }
    url = f"{sb_url}/rest/v1/collector_health"
    payload = json.dumps(record).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("apikey", sb_key)
    req.add_header("Authorization", f"Bearer {sb_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=minimal")
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def main():
    load_env()
    api_key = os.environ.get("HRFCO_API_KEY", "")
    if not api_key:
        print("⚠️  HRFCO_API_KEY 미설정 — 한강 수위 수집 건너뜀")
        print("  발급: https://www.hrfco.go.kr/web/openapiPage/certifyKey.do")
        report_health("skipped", error_message="HRFCO_API_KEY not set")
        return

    print("=" * 60)
    print("  한강 본류 수위 모니터링 — RiverWatch")
    print(f"  조회 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    try:
        data = fetch_all_waterlevel(api_key)
    except Exception as e:
        print(f"❌ API 호출 실패: {e}")
        report_health("error", error_message=str(e))
        return

    all_readings = data.get("content", [])
    if not all_readings:
        print("  ⚠️  데이터 없음")
        report_health("ok", record_count=0)
        return

    status_icon = {"danger": "🔴", "warning": "🟡", "safe": "🟢", "unknown": "⚪"}

    print(f"\n  {'관측소':<12} {'수위(m)':<10} {'계획홍수위':<10} {'상태':<8} {'비율'}")
    print("  " + "-" * 55)

    db_records = []

    for r in all_readings:
        code = r.get("wlobscd", "")
        if code not in HANGANG_STATIONS:
            continue

        stn = HANGANG_STATIONS[code]
        wl = r.get("wl", "0")
        ymdhm = r.get("ymdhm", "")

        try:
            wl_float = float(wl)
        except (ValueError, TypeError):
            continue

        status, ratio = water_level_status(wl_float, stn["pfh"])
        icon = status_icon.get(status, "⚪")
        print(f"  {stn['name']:<12} {wl_float:>8.2f}   {stn['pfh']:>8.2f}   {icon} {status:<6} {ratio:.1f}%")

        measured_at = None
        if ymdhm and len(ymdhm) == 12:
            try:
                measured_at = datetime.strptime(ymdhm, "%Y%m%d%H%M").isoformat()
            except ValueError:
                measured_at = ymdhm

        if not measured_at:
            measured_at = datetime.now().isoformat()

        water_cm = wl_float * 100
        pfh_cm = stn["pfh"] * 100

        db_records.append({
            "station": stn["name"],
            "river": "한강",
            "gu": stn["gu"],
            "water_level": round(water_cm, 1),
            "embankment_height": round(pfh_cm, 1),
            "level_ratio": round(ratio, 1),
            "status": status,
            "measured_at": measured_at,
            "collected_at": datetime.now().isoformat(),
        })

    print()

    if db_records:
        saved = save_to_supabase(db_records)
        if saved:
            print(f"  💾 Supabase 저장 완료: {saved}건 (한강 본류)")
        report_health("ok", record_count=saved)
    else:
        print("  ⚠️  서울 구간 관측소 데이터 없음")
        report_health("ok", record_count=0)

    print()


if __name__ == "__main__":
    main()

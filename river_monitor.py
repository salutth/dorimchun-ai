"""
서울시 하천 수위 모니터링 + Supabase 자동 저장
- 입력: 서울시 열린데이터 API (실시간 하천 수위)
- 처리: API 호출 → 수위 데이터 추출 + 위험 수준 판단
- 출력: 터미널 표시 + Supabase river_readings 테이블 저장
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()


def fetch_river_data(api_key):
    url = f"https://openAPI.seoul.go.kr:8088/{api_key}/json/ListRiverStageService/1/100/"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def water_level_status(current, embankment):
    try:
        ratio = float(current) / float(embankment) * 100
        if ratio >= 80:
            return "danger", ratio
        elif ratio >= 50:
            return "warning", ratio
        else:
            return "safe", ratio
    except (ValueError, ZeroDivisionError):
        return "unknown", 0


STATUS_DISPLAY = {
    "danger": "\U0001f534 위험",
    "warning": "\U0001f7e1 주의",
    "safe": "\U0001f7e2 안전",
    "unknown": "⚪ 측정불가",
}


def save_to_supabase(records):
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")
    if not supabase_url or not supabase_key:
        print("  [Supabase] URL/KEY 없음 — 저장 건너뜀")
        return 0

    url = f"{supabase_url}/rest/v1/river_readings"
    payload = json.dumps(records).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("apikey", supabase_key)
    req.add_header("Authorization", f"Bearer {supabase_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=minimal,resolution=ignore-duplicates")
    req.add_header("On-Conflict", "station,measured_at")

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
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")
    if not supabase_url or not supabase_key:
        return

    record = {
        "collector": "river_monitor",
        "status": status,
        "record_count": record_count,
        "error_message": error_message,
    }
    url = f"{supabase_url}/rest/v1/collector_health"
    payload = json.dumps(record).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("apikey", supabase_key)
    req.add_header("Authorization", f"Bearer {supabase_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=minimal")
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def main():
    load_env()
    api_key = os.environ.get("SEOUL_API_KEY", "")
    if not api_key:
        print("❌ SEOUL_API_KEY가 .env 파일에 없습니다.")
        return

    print("=" * 60)
    print("  서울시 하천 수위 모니터링 — RiverWatch")
    print(f"  조회 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    try:
        data = fetch_river_data(api_key)
    except Exception as e:
        print(f"❌ API 호출 실패: {e}")
        report_health("error", error_message=str(e))
        return

    service = data.get("ListRiverStageService", {})
    result = service.get("RESULT", {})
    if result.get("CODE") != "INFO-000":
        print(f"❌ API 오류: {result.get('MESSAGE')}")
        return

    rows = service.get("row", [])
    total = service.get("list_total_count", 0)
    print(f"\n  총 {total}개 관측소\n")
    header = f"  {'관측소':<8} {'하천':<8} {'구':<6} {'수위(cm)':<10} {'제방(cm)':<10} {'상태':<10} {'비율'}"
    print(header)
    print("  " + "-" * 72)

    danger_count = 0
    db_records = []

    for r in rows:
        name = r.get("WATG_NM", "").strip()
        river = r.get("RVR_NM", "").strip()
        gu = r.get("GU_OFC_NM", "").strip()
        level = r.get("RLTM_RVR_WATL_CNT", "0")
        embankment = r.get("EBM_HGT", "0")
        measure_time = r.get("DTRSM_DATA_CLCT_TM", "")
        status, ratio = water_level_status(level, embankment)

        if status == "danger":
            danger_count += 1

        display = STATUS_DISPLAY.get(status, status)
        print(f"  {name:<8} {river:<8} {gu:<6} {level:>8}   {embankment:>8}   {display:<10} {ratio:.1f}%")

        measured_at = None
        if measure_time:
            try:
                measured_at = datetime.strptime(measure_time, "%Y-%m-%d %H:%M").isoformat()
            except ValueError:
                measured_at = measure_time

        db_records.append({
            "station": name,
            "river": river,
            "gu": gu,
            "water_level": float(level) if level else 0,
            "embankment_height": float(embankment) if embankment else 0,
            "level_ratio": round(ratio, 1),
            "status": status,
            "measured_at": measured_at,
        })

    first_measure = rows[0].get("DTRSM_DATA_CLCT_TM", "") if rows else ""
    print(f"\n  측정 시각: {first_measure}")

    if danger_count > 0:
        print(f"\n  ⚠️  위험 수준 관측소: {danger_count}개 — 주의가 필요합니다!")
    else:
        print("\n  ✅ 전체 관측소 안전 수준입니다.")

    saved = save_to_supabase(db_records)
    if saved:
        print(f"  \U0001f4be Supabase 저장 완료: {saved}건")
    report_health("ok", record_count=saved)
    print()


if __name__ == "__main__":
    main()

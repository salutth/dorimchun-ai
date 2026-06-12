"""
서울시 하천 수위 모니터링 스크립트
- 입력: 서울시 열린데이터 API (실시간 하천 수위)
- 처리: API 호출 → 하천별 수위 데이터 추출 + 위험 수준 판단
- 출력: 터미널에 하천별 수위 현황 요약 표시
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

def load_api_key():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
    return os.environ.get("SEOUL_API_KEY", "")

def fetch_river_data(api_key):
    url = f"http://openAPI.seoul.go.kr:8088/{api_key}/json/ListRiverStageService/1/100/"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

def water_level_status(current, embankment):
    try:
        ratio = float(current) / float(embankment) * 100
        if ratio >= 80:
            return "🔴 위험", ratio
        elif ratio >= 50:
            return "🟡 주의", ratio
        else:
            return "🟢 안전", ratio
    except (ValueError, ZeroDivisionError):
        return "⚪ 측정불가", 0

def main():
    api_key = load_api_key()
    if not api_key:
        print("❌ SEOUL_API_KEY가 .env 파일에 없습니다.")
        return

    print("=" * 60)
    print(f"  서울시 하천 수위 모니터링")
    print(f"  조회 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    try:
        data = fetch_river_data(api_key)
    except Exception as e:
        print(f"❌ API 호출 실패: {e}")
        return

    service = data.get("ListRiverStageService", {})
    result = service.get("RESULT", {})
    if result.get("CODE") != "INFO-000":
        print(f"❌ API 오류: {result.get('MESSAGE')}")
        return

    rows = service.get("row", [])
    total = service.get("list_total_count", 0)
    print(f"\n  총 {total}개 관측소\n")
    print(f"  {'관측소':<8} {'하천':<8} {'구':<6} {'수위(cm)':<10} {'제방(cm)':<10} {'상태':<10} {'비율'}")
    print("  " + "-" * 72)

    danger_count = 0
    for r in rows:
        name = r.get("WATG_NM", "")
        river = r.get("RVR_NM", "")
        gu = r.get("GU_OFC_NM", "")
        level = r.get("RLTM_RVR_WATL_CNT", "0")
        embankment = r.get("EBM_HGT", "0")
        status, ratio = water_level_status(level, embankment)

        if "위험" in status:
            danger_count += 1

        print(f"  {name:<8} {river:<8} {gu:<6} {level:>8}   {embankment:>8}   {status:<10} {ratio:.1f}%")

    measure_time = rows[0].get("DTRSM_DATA_CLCT_TM", "") if rows else ""
    print(f"\n  측정 시각: {measure_time}")

    if danger_count > 0:
        print(f"\n  ⚠️  위험 수준 관측소: {danger_count}개 — 주의가 필요합니다!")
    else:
        print(f"\n  ✅ 전체 관측소 안전 수준입니다.")
    print()

if __name__ == "__main__":
    main()

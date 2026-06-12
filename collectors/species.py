"""
도림천 생물 관찰 데이터 수집기 (iNaturalist API)
- 입력: iNaturalist API (도림천 반경 2km 최근 관찰)
- 처리: 관찰 데이터 → 외래종 판별 → Supabase 저장
- 출력: 터미널 표시 + species_observations 테이블 저장
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DORIMCHEON_LAT = 37.4838
DORIMCHEON_LNG = 126.9295
SEARCH_RADIUS_KM = 2

INVASIVE_SPECIES = {
    "Trachemys scripta",
    "Micropterus salmoides",
    "Lepomis macrochirus",
    "Myocastor coypus",
    "Rana catesbeiana",
    "Lithobates catesbeianus",
    "Procambarus clarkii",
    "Ambrosia artemisiifolia",
    "Solidago altissima",
    "Humulus japonicus",
    "Rumex acetosella",
    "Ageratina altissima",
    "Paspalum distichum",
    "Alternanthera philoxeroides",
    "Ludwigia grandiflora",
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


def fetch_observations(lat, lng, radius_km, days=30):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = urllib.parse.urlencode({
        "lat": lat,
        "lng": lng,
        "radius": radius_km,
        "d1": since,
        "order": "desc",
        "order_by": "observed_on",
        "per_page": 50,
        "quality_grade": "research,needs_id",
    })
    url = f"https://api.inaturalist.org/v1/observations?{params}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "RiverWatch/1.0 (citizen-science)")

    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save_to_supabase(records):
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")
    if not supabase_url or not supabase_key:
        print("  [Supabase] URL/KEY 없음 — 저장 건너뜀")
        return 0

    url = f"{supabase_url}/rest/v1/species_observations"
    payload = json.dumps(records).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("apikey", supabase_key)
    req.add_header("Authorization", f"Bearer {supabase_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=minimal")

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


def main():
    load_env()

    print("=" * 60)
    print("  도림천 생물 관찰 수집기 — RiverWatch Agent 1")
    print(f"  위치: {DORIMCHEON_LAT}, {DORIMCHEON_LNG} (반경 {SEARCH_RADIUS_KM}km)")
    print(f"  조회: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    try:
        data = fetch_observations(DORIMCHEON_LAT, DORIMCHEON_LNG, SEARCH_RADIUS_KM)
    except Exception as e:
        print(f"❌ iNaturalist API 호출 실패: {e}")
        return

    results = data.get("results", [])
    total = data.get("total_results", 0)
    print(f"\n  총 {total}건 관찰 (최근 30일, 최대 50건 표시)\n")

    if not results:
        print("  관찰 데이터 없음")
        return

    print(f"  {'종명':<28} {'일반명':<16} {'관찰일':<12} {'외래종':<6} {'품질'}")
    print("  " + "-" * 76)

    db_records = []
    invasive_count = 0

    for obs in results:
        taxon = obs.get("taxon") or {}
        species_name = taxon.get("name", "미확인")
        common = taxon.get("preferred_common_name", "")
        taxon_id = taxon.get("id")
        lat = obs.get("geojson", {}).get("coordinates", [0, 0])[1] if obs.get("geojson") else None
        lng = obs.get("geojson", {}).get("coordinates", [0, 0])[0] if obs.get("geojson") else None
        observed = obs.get("observed_on", "")
        quality = obs.get("quality_grade", "")
        photos = obs.get("photos", [])
        photo_url = photos[0].get("url", "").replace("square", "medium") if photos else ""
        observer = obs.get("user", {}).get("login", "")

        is_invasive = species_name in INVASIVE_SPECIES
        if is_invasive:
            invasive_count += 1

        invasive_mark = "\U0001f6a8" if is_invasive else ""
        print(f"  {species_name:<28} {common:<16} {observed:<12} {invasive_mark:<6} {quality}")

        observed_at = None
        if observed:
            try:
                observed_at = datetime.strptime(observed, "%Y-%m-%d").isoformat()
            except ValueError:
                observed_at = observed

        db_records.append({
            "taxon_name": species_name,
            "common_name": common,
            "taxon_id": taxon_id,
            "latitude": lat,
            "longitude": lng,
            "river": "도림천",
            "photo_url": photo_url,
            "observer": observer,
            "source": "inaturalist",
            "is_invasive": is_invasive,
            "observed_at": observed_at,
        })

    print(f"\n  총 관찰: {len(results)}건")
    if invasive_count > 0:
        print(f"  \U0001f6a8 외래종 감지: {invasive_count}건 — 주의!")
    else:
        print("  ✅ 외래종 미감지")

    saved = save_to_supabase(db_records)
    if saved:
        print(f"  \U0001f4be Supabase 저장 완료: {saved}건")
    print()


if __name__ == "__main__":
    main()

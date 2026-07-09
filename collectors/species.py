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

SEARCH_RADIUS_KM = 2

RIVER_LOCATIONS = {
    "도림천": {"lat": 37.4838, "lng": 126.9295},
    "안양천": {"lat": 37.4750, "lng": 126.8870},
    "중랑천": {"lat": 37.5950, "lng": 127.0500},
    "탄천":   {"lat": 37.5050, "lng": 127.0780},
    "불광천": {"lat": 37.5900, "lng": 126.9200},
    "홍제천": {"lat": 37.5750, "lng": 126.9450},
    "방학천": {"lat": 37.6550, "lng": 127.0280},
    "우이천": {"lat": 37.6500, "lng": 127.0130},
    "정릉천": {"lat": 37.6050, "lng": 127.0050},
    "청계천": {"lat": 37.5700, "lng": 127.0100},
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
    clean_records = []
    for r in records:
        rec = dict(r)
        rec.pop("inaturalist_id", None)
        clean_records.append(rec)
    payload = json.dumps(clean_records).encode("utf-8")
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


def report_health(status, record_count=0, error_message=None):
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")
    if not supabase_url or not supabase_key:
        return

    record = {
        "collector": "species",
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


def collect_river(river_name, lat, lng):
    print(f"\n  --- {river_name} (반경 {SEARCH_RADIUS_KM}km) ---")
    try:
        data = fetch_observations(lat, lng, SEARCH_RADIUS_KM)
    except Exception as e:
        print(f"  API 호출 실패: {e}")
        return []

    results = data.get("results", [])
    if not results:
        print(f"  관찰 데이터 없음")
        return []

    db_records = []
    invasive_count = 0

    for obs in results:
        taxon = obs.get("taxon") or {}
        species_name = taxon.get("name", "미확인")
        common = taxon.get("preferred_common_name", "")
        taxon_id = taxon.get("id")
        obs_lat = obs.get("geojson", {}).get("coordinates", [0, 0])[1] if obs.get("geojson") else None
        obs_lng = obs.get("geojson", {}).get("coordinates", [0, 0])[0] if obs.get("geojson") else None
        observed = obs.get("observed_on", "")
        photos = obs.get("photos") or obs.get("observation_photos") or []
        photo_url = ""
        if photos:
            p = photos[0]
            if isinstance(p, dict):
                raw = p.get("url") or p.get("photo", {}).get("url", "")
                if raw:
                    photo_url = raw.replace("square", "medium").replace("small", "medium")
        if not photo_url and obs.get("id"):
            photo_url = f"https://inaturalist-open-data.s3.amazonaws.com/photos/{obs['id']}/medium.jpg"
        observer = obs.get("user", {}).get("login", "")

        is_invasive = species_name in INVASIVE_SPECIES
        if is_invasive:
            invasive_count += 1

        observed_at = None
        if observed:
            try:
                observed_at = datetime.strptime(observed, "%Y-%m-%d").isoformat()
            except ValueError:
                observed_at = observed

        db_records.append({
            "inaturalist_id": obs.get("id"),
            "taxon_name": species_name,
            "common_name": common,
            "taxon_id": taxon_id,
            "latitude": obs_lat,
            "longitude": obs_lng,
            "river": river_name,
            "photo_url": photo_url,
            "observer": observer,
            "source": "inaturalist",
            "is_invasive": is_invasive,
            "observed_at": observed_at,
        })

    print(f"  관찰 {len(results)}건 | 외래종 {invasive_count}건")
    return db_records


def main():
    load_env()

    print("=" * 60)
    print("  서울 10개 하천 생물 관찰 수집기 — RiverWatch Agent 1")
    print(f"  조회: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    all_records = []
    for river_name, coords in RIVER_LOCATIONS.items():
        records = collect_river(river_name, coords["lat"], coords["lng"])
        all_records.extend(records)

    if not all_records:
        print("\n  전체 관찰 데이터 없음")
        report_health("ok", record_count=0)
        return

    unique_species = set(r["taxon_name"] for r in all_records if r["taxon_name"] != "미확인")
    invasive_total = sum(1 for r in all_records if r["is_invasive"])

    print(f"\n  === 전체 요약 ===")
    print(f"  총 관찰: {len(all_records)}건 | 고유 종: {len(unique_species)}종 | 외래종: {invasive_total}건")

    saved = save_to_supabase(all_records)
    if saved:
        print(f"  Supabase 저장 완료: {saved}건")
    report_health("ok", record_count=saved)
    print()


if __name__ == "__main__":
    main()

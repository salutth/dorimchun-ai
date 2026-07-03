"""
EHI 생태건강성지수 산출 Agent (RiverWatch Agent 2)
- 입력: Supabase의 species_observations + river_readings
- 처리: 생물다양성 + 수위안정성 + 외래종비율 → EHI 종합점수
- 출력: 하천별 EHI 등급 (A~E) → Supabase ehi_scores 테이블 저장

EHI 산출 공식 (환경부 가이드라인 기반 간이 모델):
  EHI = (생물다양성 30%) + (수위안정성 30%) + (외래종부재 20%) + (관찰빈도 20%)
  등급: A(>=80) B(>=60) C(>=40) D(>=20) E(<20)
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EHI_WEIGHTS = {
    "biodiversity": 0.30,
    "water_stability": 0.30,
    "non_invasive": 0.20,
    "observation_freq": 0.20,
}

GRADE_THRESHOLDS = [
    (80, "A", "매우좋음"),
    (60, "B", "좋음"),
    (40, "C", "보통"),
    (20, "D", "나쁨"),
    (0,  "E", "매우나쁨"),
]

RIVERS = ["도림천", "안양천", "중랑천", "탄천", "불광천", "홍제천",
           "방학천", "우이천", "정릉천", "청계천", "양재천", "성북천",
           "묵동천", "전농천", "월계천", "반포천", "여의천", "봉원천",
           "녹번천", "세곡천", "내부천"]


def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()


def supabase_get(table, params=""):
    url_base = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url_base or not key:
        return []

    url = f"{url_base}/rest/v1/{table}?{params}"
    req = urllib.request.Request(url)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [Supabase] 조회 실패: {e}")
        return []


def supabase_post(table, records):
    url_base = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url_base or not key or not records:
        return 0

    conflict = "river,calculated_at" if table == "ehi_scores" else ""
    qs = f"?on_conflict={conflict}" if conflict else ""
    url = f"{url_base}/rest/v1/{table}{qs}"
    payload = json.dumps(records).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
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


def calc_biodiversity_score(species_list):
    unique_species = set()
    for s in species_list:
        name = s.get("taxon_name", "")
        if name and name != "미확인":
            unique_species.add(name)

    count = len(unique_species)
    if count >= 20:
        return 100
    elif count >= 15:
        return 85
    elif count >= 10:
        return 70
    elif count >= 5:
        return 50
    elif count >= 2:
        return 30
    elif count >= 1:
        return 15
    return 0


def calc_water_stability_score(readings):
    if not readings:
        return 50

    ratios = [r.get("level_ratio", 0) for r in readings]
    avg_ratio = sum(ratios) / len(ratios) if ratios else 0
    danger_count = sum(1 for r in readings if r.get("status") == "danger")

    if danger_count > 0:
        score = max(0, 40 - danger_count * 15)
    elif avg_ratio >= 70:
        score = 30
    elif avg_ratio >= 50:
        score = 60
    elif avg_ratio >= 30:
        score = 80
    else:
        score = 95

    return min(100, score)


def calc_non_invasive_score(species_list):
    if not species_list:
        return 50

    total = len(species_list)
    invasive = sum(1 for s in species_list if s.get("is_invasive"))

    if total == 0:
        return 50

    invasive_ratio = invasive / total
    if invasive_ratio == 0:
        return 100
    elif invasive_ratio < 0.05:
        return 85
    elif invasive_ratio < 0.1:
        return 65
    elif invasive_ratio < 0.2:
        return 40
    else:
        return 15


def calc_observation_freq_score(species_list):
    count = len(species_list)
    if count >= 50:
        return 100
    elif count >= 30:
        return 85
    elif count >= 15:
        return 70
    elif count >= 5:
        return 50
    elif count >= 1:
        return 25
    return 0


def get_grade(score):
    for threshold, grade, label in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade, label
    return "E", "매우나쁨"


GRADE_COLORS = {"A": "\U0001f7e2", "B": "\U0001f7e2", "C": "\U0001f7e1", "D": "\U0001f534", "E": "\U0001f534"}


def main():
    load_env()

    print("=" * 60)
    print("  EHI 생태건강성지수 산출 — RiverWatch Agent 2")
    print(f"  산출 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    species_all = supabase_get("species_observations",
        "select=taxon_name,river,is_invasive,observed_at&order=observed_at.desc&limit=500")
    readings_all = supabase_get("river_readings",
        "select=station,river,water_level,level_ratio,status&order=id.desc&limit=200")

    species_by_river = {}
    for s in species_all:
        river = s.get("river", "")
        if river:
            species_by_river.setdefault(river, []).append(s)

    readings_by_river = {}
    for r in readings_all:
        river = r.get("river", "")
        if river:
            readings_by_river.setdefault(river, []).append(r)

    all_rivers = set(list(species_by_river.keys()) + list(readings_by_river.keys()))

    if not all_rivers:
        print("\n  데이터 없음 — 수위/생물 데이터를 먼저 수집하세요.")
        return

    print(f"\n  {'하천':<10} {'생물다양':<8} {'수위안정':<8} {'외래종부재':<10} {'관찰빈도':<8} {'EHI':<6} {'등급'}")
    print("  " + "-" * 68)

    ehi_records = []

    for river in sorted(all_rivers):
        sp = species_by_river.get(river, [])
        rd = readings_by_river.get(river, [])

        bio = calc_biodiversity_score(sp)
        water = calc_water_stability_score(rd)
        non_inv = calc_non_invasive_score(sp)
        obs_freq = calc_observation_freq_score(sp)

        ehi = (
            bio * EHI_WEIGHTS["biodiversity"]
            + water * EHI_WEIGHTS["water_stability"]
            + non_inv * EHI_WEIGHTS["non_invasive"]
            + obs_freq * EHI_WEIGHTS["observation_freq"]
        )
        ehi = round(ehi, 1)
        grade, grade_label = get_grade(ehi)
        icon = GRADE_COLORS.get(grade, "")

        print(f"  {river:<10} {bio:>5}    {water:>5}    {non_inv:>5}      {obs_freq:>5}    {ehi:>5}  {icon} {grade} ({grade_label})")

        ehi_records.append({
            "river": river,
            "biodiversity_score": bio,
            "water_stability_score": water,
            "non_invasive_score": non_inv,
            "observation_freq_score": obs_freq,
            "ehi_score": ehi,
            "grade": grade,
            "species_count": len(set(s.get("taxon_name", "") for s in sp)),
            "reading_count": len(rd),
            "calculated_at": datetime.now().isoformat(),
        })

    print(f"\n  산출 기준: 생물다양성 {int(EHI_WEIGHTS['biodiversity']*100)}% + "
          f"수위안정성 {int(EHI_WEIGHTS['water_stability']*100)}% + "
          f"외래종부재 {int(EHI_WEIGHTS['non_invasive']*100)}% + "
          f"관찰빈도 {int(EHI_WEIGHTS['observation_freq']*100)}%")

    saved = supabase_post("ehi_scores", ehi_records)
    if saved:
        print(f"  \U0001f4be Supabase 저장 완료: {saved}건")
    elif ehi_records:
        print("  [참고] ehi_scores 테이블이 없으면 아래 SQL을 Supabase에서 실행하세요.")
    print()


if __name__ == "__main__":
    main()

"""
정책보고서 생성 Agent (RiverWatch Agent 4)
- 입력: Supabase의 ehi_scores + species_observations + river_readings + invasive_alerts
- 처리: 데이터 집계 → 마크다운 보고서 생성
- 출력: reports/ 폴더에 월간 생태 보고서 저장 + Supabase 업로드
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

GRADE_EMOJI = {"A": "🟢", "B": "🟢", "C": "🟡", "D": "🔴", "E": "🔴"}
GRADE_DESC = {
    "A": "매우 건강한 생태계",
    "B": "양호한 생태계",
    "C": "보통 수준, 관리 필요",
    "D": "생태계 열악, 개선 시급",
    "E": "매우 열악, 긴급 조치 필요",
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
        print(f"  [Supabase] {table} 조회 실패: {e}")
        return []


def generate_report():
    now = datetime.now()
    month_str = now.strftime("%Y-%m")
    date_str = now.strftime("%Y-%m-%d %H:%M")

    ehi_scores = supabase_get("ehi_scores",
        "select=*&order=calculated_at.desc&limit=30")
    species = supabase_get("species_observations",
        "select=taxon_name,river,is_invasive,observed_at&order=observed_at.desc&limit=500")
    readings = supabase_get("river_readings",
        "select=station,river,water_level,level_ratio,status,measured_at&order=id.desc&limit=200")
    alerts = supabase_get("invasive_alerts",
        "select=species_name,river,alert_level,created_at&order=created_at.desc&limit=50")

    latest_ehi = {}
    for score in ehi_scores:
        river = score.get("river", "")
        if river and river not in latest_ehi:
            latest_ehi[river] = score

    species_by_river = {}
    for s in species:
        river = s.get("river", "")
        if river:
            species_by_river.setdefault(river, []).append(s)

    danger_stations = [r for r in readings if r.get("status") == "danger"]
    warning_stations = [r for r in readings if r.get("status") == "warning"]
    seen_stations = set()
    unique_danger = []
    for r in danger_stations:
        if r["station"] not in seen_stations:
            seen_stations.add(r["station"])
            unique_danger.append(r)

    total_species = len(set(s.get("taxon_name", "") for s in species if s.get("taxon_name")))
    total_invasive = sum(1 for s in species if s.get("is_invasive"))
    total_observations = len(species)

    avg_ehi = 0
    if latest_ehi:
        scores = [v.get("ehi_score", 0) for v in latest_ehi.values() if v.get("ehi_score")]
        avg_ehi = sum(scores) / len(scores) if scores else 0

    best_river = max(latest_ehi.items(), key=lambda x: x[1].get("ehi_score", 0))[0] if latest_ehi else "데이터 없음"
    worst_river = min(latest_ehi.items(), key=lambda x: x[1].get("ehi_score", 0))[0] if latest_ehi else "데이터 없음"

    report = f"""---
title: "서울 하천 생태 월간 보고서 — {month_str}"
date: {date_str}
type: policy_report
---

# 서울 하천 생태 월간 보고서

> 생성일: {date_str} | RiverWatch Agent 4 자동 생성

---

## 1. 요약 (Executive Summary)

| 지표 | 값 |
|------|-----|
| 모니터링 하천 | {len(latest_ehi)}개 |
| 평균 EHI | {avg_ehi:.1f}점 |
| 관찰된 종 수 | {total_species}종 |
| 총 관찰 건수 | {total_observations}건 |
| 외래종 감지 | {total_invasive}건 |
| 위험 관측소 | {len(unique_danger)}개소 |
| 최우수 하천 | {best_river} |
| 최저 하천 | {worst_river} |

---

## 2. 하천별 생태건강도 (EHI)

| 하천 | EHI | 등급 | 생물다양성 | 수위안정 | 외래종부재 | 관찰빈도 | 종수 |
|------|-----|------|-----------|---------|-----------|---------|------|
"""

    for river in sorted(latest_ehi.keys()):
        e = latest_ehi[river]
        grade = e.get("grade", "?")
        emoji = GRADE_EMOJI.get(grade, "⬜")
        report += (f"| {river} | {e.get('ehi_score', 0):.1f} | {emoji} {grade} "
                   f"| {e.get('biodiversity_score', 0):.0f} "
                   f"| {e.get('water_stability_score', 0):.0f} "
                   f"| {e.get('non_invasive_score', 0):.0f} "
                   f"| {e.get('observation_freq_score', 0):.0f} "
                   f"| {e.get('species_count', 0)} |\n")

    report += """
---

## 3. 수위 위험 현황

"""
    if unique_danger:
        report += "| 관측소 | 하천 | 수위비율 | 상태 |\n|--------|------|---------|------|\n"
        for r in unique_danger[:10]:
            report += f"| {r['station']} | {r['river']} | {r.get('level_ratio', 0)}% | 위험 |\n"
    else:
        report += "현재 위험 수준 관측소 없음.\n"

    report += """
---

## 4. 외래종 경보 현황

"""
    if alerts:
        report += "| 종명 | 하천 | 경보 수준 | 감지일 |\n|------|------|---------|--------|\n"
        for a in alerts[:10]:
            level = {"critical": "긴급", "warning": "주의", "info": "관찰"}.get(a.get("alert_level", ""), "?")
            date = a.get("created_at", "")[:10]
            report += f"| {a.get('species_name', '')} | {a.get('river', '')} | {level} | {date} |\n"
    else:
        report += "현재 외래종 경보 없음. 생태계 안정 상태.\n"

    report += """
---

## 5. 생물다양성 현황

"""
    for river in sorted(species_by_river.keys()):
        sp_list = species_by_river[river]
        unique = set(s.get("taxon_name", "") for s in sp_list if s.get("taxon_name"))
        invasive = sum(1 for s in sp_list if s.get("is_invasive"))
        report += f"- **{river}**: {len(unique)}종 관찰, 외래종 {invasive}건\n"

    if not species_by_river:
        report += "생물 관찰 데이터 축적 필요.\n"

    report += """
---

## 6. 정책 제언

"""
    recommendations = []

    if avg_ehi < 40:
        recommendations.append("- 전체 평균 EHI가 40점 미만으로 **긴급 생태복원 사업** 검토 필요")
    elif avg_ehi < 60:
        recommendations.append("- 전체 평균 EHI가 보통 수준으로 **지속적 모니터링 강화** 권고")

    if total_invasive > 0:
        recommendations.append(f"- 외래종 {total_invasive}건 감지 — **생태교란종 제거 작업** 우선 시행")

    if len(unique_danger) >= 3:
        recommendations.append(f"- 위험 관측소 {len(unique_danger)}개소 — **하천 범람 대비 점검** 시급")

    low_bio_rivers = [r for r, e in latest_ehi.items() if e.get("biodiversity_score", 0) < 30]
    if low_bio_rivers:
        recommendations.append(f"- 생물다양성 취약 하천({', '.join(low_bio_rivers)}) — **시민과학 관찰 캠페인** 확대")

    if not recommendations:
        recommendations.append("- 현재 생태계 양호, **정기 모니터링 유지** 권고")

    report += "\n".join(recommendations)

    report += f"""

---

## 7. 데이터 출처

- 수위 데이터: 서울시 열린데이터 API (`openAPI.seoul.go.kr`)
- 생물 관찰: iNaturalist API (`api.inaturalist.org`)
- 생태건강도: RiverWatch EHI 모델 (환경부 가이드라인 기반)
- 외래종 DB: 환경부 지정 생태교란종 15종

---

*이 보고서는 RiverWatch Agent 4에 의해 자동 생성되었습니다.*
*문의: 도깨비3.0 팀 (AI활동가 1기)*
"""

    return report, month_str


def main():
    load_env()

    print("=" * 60)
    print("  정책보고서 생성 — RiverWatch Agent 4")
    print(f"  생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    report, month_str = generate_report()

    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"report_{month_str}.md"
    filepath = os.path.join(REPORTS_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n  보고서 저장: {filepath}")
    print(f"  파일 크기: {len(report.encode('utf-8')):,} bytes")

    lines = report.split("\n")
    for line in lines[:30]:
        print(f"  {line}")
    if len(lines) > 30:
        print(f"  ... ({len(lines) - 30}줄 더)")

    print()


if __name__ == "__main__":
    main()

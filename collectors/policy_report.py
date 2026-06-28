"""
RiverWatch Auto Report Generator (Phase 2)
- Supabase 전체 데이터 기반 주간/월간 종합 분석 보고서
- 수위, 생물, EHI, 수질 TMS, 문화재, 기상 통합 분석
- JSON + Markdown 출력 (analysis.html 뷰어 연동)
"""

import json
import os
import sys
import urllib.request
import ssl
from datetime import datetime, timedelta
from collections import Counter

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
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [Supabase] {table} 조회 실패: {e}")
        return []


def safe_float(val, default=0):
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def analyze_water_quality(wq_data):
    if not wq_data:
        return None

    by_station = {}
    for r in wq_data:
        name = r.get("station_name", "")
        if name:
            by_station.setdefault(name, []).append(r)

    station_summaries = []
    for station, records in by_station.items():
        ph_vals = [safe_float(r.get("ph")) for r in records if r.get("ph")]
        do_vals = [safe_float(r.get("dissolved_oxygen")) for r in records if r.get("dissolved_oxygen")]
        temp_vals = [safe_float(r.get("water_temp")) for r in records if r.get("water_temp")]
        tn_vals = [safe_float(r.get("total_nitrogen")) for r in records if r.get("total_nitrogen")]
        tp_vals = [safe_float(r.get("total_phosphorus")) for r in records if r.get("total_phosphorus")]

        avg = lambda vals: round(sum(vals) / len(vals), 2) if vals else None

        grades = [r.get("do_grade", "") for r in records if r.get("do_grade")]
        grade_counts = Counter(grades)
        dominant_grade = grade_counts.most_common(1)[0][0] if grade_counts else "측정불가"

        summary = {
            "station": station,
            "count": len(records),
            "ph_avg": avg(ph_vals),
            "ph_min": round(min(ph_vals), 2) if ph_vals else None,
            "ph_max": round(max(ph_vals), 2) if ph_vals else None,
            "do_avg": avg(do_vals),
            "do_min": round(min(do_vals), 2) if do_vals else None,
            "do_max": round(max(do_vals), 2) if do_vals else None,
            "temp_avg": avg(temp_vals),
            "tn_avg": avg(tn_vals),
            "tp_avg": avg(tp_vals),
            "dominant_grade": dominant_grade,
        }
        station_summaries.append(summary)

    all_do = [safe_float(r.get("dissolved_oxygen")) for r in wq_data if r.get("dissolved_oxygen")]
    all_ph = [safe_float(r.get("ph")) for r in wq_data if r.get("ph")]

    ph_alert = any(s["ph_min"] and (s["ph_min"] < 6.5 or s["ph_max"] > 8.5) for s in station_summaries if s["ph_min"] and s["ph_max"])
    do_alert = any(s["do_min"] and s["do_min"] < 5.0 for s in station_summaries if s["do_min"])

    return {
        "stations": station_summaries,
        "total_records": len(wq_data),
        "avg_do": round(sum(all_do) / len(all_do), 2) if all_do else None,
        "avg_ph": round(sum(all_ph) / len(all_ph), 2) if all_ph else None,
        "ph_alert": ph_alert,
        "do_alert": do_alert,
    }


def analyze_species(species_data):
    if not species_data:
        return None

    unique_species = set()
    by_river = {}
    invasive_list = []
    by_source = Counter()

    for s in species_data:
        name = s.get("taxon_name", "")
        river = s.get("river", "")
        if name:
            unique_species.add(name)
        if river:
            by_river.setdefault(river, set()).add(name)
        if s.get("is_invasive"):
            invasive_list.append({"name": name, "river": river})
        by_source[s.get("source", "unknown")] += 1

    river_diversity = [
        {"river": r, "species_count": len(sp)}
        for r, sp in sorted(by_river.items(), key=lambda x: -len(x[1]))
    ]

    return {
        "total_species": len(unique_species),
        "total_observations": len(species_data),
        "invasive_count": len(invasive_list),
        "invasive_species": invasive_list[:10],
        "river_diversity": river_diversity,
        "top_species": Counter(s.get("taxon_name", "") for s in species_data if s.get("taxon_name")).most_common(10),
        "sources": dict(by_source),
    }


def analyze_ehi(ehi_data):
    if not ehi_data:
        return None

    latest = {}
    for e in ehi_data:
        river = e.get("river", "")
        if river and river not in latest:
            latest[river] = e

    scores = [safe_float(v.get("ehi_score")) for v in latest.values() if v.get("ehi_score")]
    avg_ehi = round(sum(scores) / len(scores), 1) if scores else 0

    grade_dist = Counter(v.get("grade", "?") for v in latest.values())

    river_scores = []
    for river, e in sorted(latest.items(), key=lambda x: -safe_float(x[1].get("ehi_score"))):
        river_scores.append({
            "river": river,
            "score": safe_float(e.get("ehi_score")),
            "grade": e.get("grade", "?"),
            "biodiversity": safe_float(e.get("biodiversity_score")),
            "water_stability": safe_float(e.get("water_stability_score")),
            "non_invasive": safe_float(e.get("non_invasive_score")),
            "obs_freq": safe_float(e.get("observation_freq_score")),
            "species_count": e.get("species_count", 0),
        })

    best = river_scores[0] if river_scores else None
    worst = river_scores[-1] if river_scores else None

    return {
        "avg_ehi": avg_ehi,
        "river_count": len(latest),
        "grade_distribution": dict(grade_dist),
        "river_scores": river_scores,
        "best_river": best,
        "worst_river": worst,
    }


def analyze_water_level(readings):
    if not readings:
        return None

    danger = [r for r in readings if r.get("status") == "danger"]
    warning = [r for r in readings if r.get("status") == "warning"]

    seen = set()
    unique_danger = []
    for r in danger:
        key = r.get("station", "")
        if key not in seen:
            seen.add(key)
            unique_danger.append({
                "station": r["station"],
                "river": r.get("river", ""),
                "level_ratio": r.get("level_ratio", 0),
            })

    stations_count = len(set(r.get("station", "") for r in readings))

    return {
        "total_readings": len(readings),
        "stations": stations_count,
        "danger_count": len(unique_danger),
        "warning_count": len(set(r.get("station", "") for r in warning)),
        "danger_stations": unique_danger[:10],
    }


def analyze_weather(weather_data):
    if not weather_data:
        return None

    rain_days = sum(1 for w in weather_data if safe_float(w.get("rain_prob", 0)) >= 60)
    high_temps = [safe_float(w.get("max_temp")) for w in weather_data if w.get("max_temp")]
    low_temps = [safe_float(w.get("min_temp")) for w in weather_data if w.get("min_temp")]

    return {
        "total_forecasts": len(weather_data),
        "rain_risk_days": rain_days,
        "avg_high": round(sum(high_temps) / len(high_temps), 1) if high_temps else None,
        "avg_low": round(sum(low_temps) / len(low_temps), 1) if low_temps else None,
    }


def generate_policy_recommendations(ehi_analysis, wq_analysis, species_analysis, level_analysis):
    recs = []

    if ehi_analysis:
        avg = ehi_analysis["avg_ehi"]
        if avg < 40:
            recs.append({
                "priority": "긴급",
                "category": "생태복원",
                "text": f"전체 평균 EHI {avg}점 — 긴급 생태복원 사업 검토 필요",
            })
        elif avg < 60:
            recs.append({
                "priority": "주의",
                "category": "모니터링",
                "text": f"전체 평균 EHI {avg}점 — 지속적 모니터링 강화 권고",
            })
        else:
            recs.append({
                "priority": "양호",
                "category": "유지관리",
                "text": f"전체 평균 EHI {avg}점 — 현행 관리 체계 유지",
            })

        if ehi_analysis.get("worst_river"):
            w = ehi_analysis["worst_river"]
            if w["score"] < 40:
                recs.append({
                    "priority": "주의",
                    "category": "집중관리",
                    "text": f"{w['river']} EHI {w['score']}점으로 최저 — 집중 생태 복원 필요",
                })

    if species_analysis and species_analysis["invasive_count"] > 0:
        recs.append({
            "priority": "주의",
            "category": "외래종",
            "text": f"외래종 {species_analysis['invasive_count']}건 감지 — 생태교란종 제거 작업 시행 필요",
        })

    if wq_analysis:
        if wq_analysis["do_alert"]:
            recs.append({
                "priority": "긴급",
                "category": "수질",
                "text": "용존산소(DO) 5.0mg/L 미만 관측 — 수질 개선 조치 시급",
            })
        if wq_analysis["ph_alert"]:
            recs.append({
                "priority": "주의",
                "category": "수질",
                "text": "pH 정상범위(6.5~8.5) 이탈 관측 — 오염원 점검 필요",
            })

    if level_analysis and level_analysis["danger_count"] >= 3:
        recs.append({
            "priority": "긴급",
            "category": "방재",
            "text": f"위험 관측소 {level_analysis['danger_count']}개소 — 하천 범람 대비 점검 시급",
        })

    if not recs:
        recs.append({
            "priority": "양호",
            "category": "종합",
            "text": "전체적으로 양호한 상태, 정기 모니터링 유지 권고",
        })

    return recs


def render_markdown(data):
    meta = data["meta"]
    s = data["summary"]
    ehi = data.get("ehi")
    wq = data.get("water_quality")
    sp = data.get("species")
    lv = data.get("water_level")
    wx = data.get("weather")
    alerts = data.get("alerts", [])
    recs = data.get("recommendations", [])

    md = f"""---
title: "{meta['title']}"
date: {meta['generated_at']}
type: auto_analysis
---

# {meta['title']}

> {meta['generated_at']} | {meta['generator']} 자동 생성

---

## 1. 종합 요약

| 지표 | 값 |
|------|-----|
| 모니터링 하천 | {s['rivers_monitored']}개 |
| 평균 EHI | {s['avg_ehi']}점 |
| 관찰된 종 수 | {s['total_species']}종 |
| 총 관찰 건수 | {s['total_observations']}건 |
| 외래종 감지 | {s['invasive_count']}건 |
| 위험 관측소 | {s['danger_stations']}개소 |
| 수질 관측소 | {s['wq_stations']}개소 |
| 평균 DO | {s['wq_avg_do'] or 'N/A'} mg/L |

---

## 2. 생태건강지수 (EHI)

"""
    if ehi and ehi.get("river_scores"):
        md += "| 하천 | EHI | 등급 | 생물다양성 | 수위안정 | 외래종부재 | 종수 |\n"
        md += "|------|-----|------|-----------|---------|-----------|------|\n"
        for r in ehi["river_scores"]:
            emoji = GRADE_EMOJI.get(r["grade"], "")
            md += f"| {r['river']} | {r['score']:.1f} | {emoji} {r['grade']} | {r['biodiversity']:.0f} | {r['water_stability']:.0f} | {r['non_invasive']:.0f} | {r['species_count']} |\n"
    else:
        md += "EHI 데이터 축적 중.\n"

    md += "\n---\n\n## 3. 수질 TMS 분석\n\n"
    if wq and wq.get("stations"):
        md += "| 관측소 | 측정수 | pH(avg) | DO(avg) | 수온(avg) | T-N | T-P | 등급 |\n"
        md += "|--------|--------|---------|---------|----------|-----|-----|------|\n"
        for st in wq["stations"]:
            ph = f"{st['ph_avg']:.1f}" if st['ph_avg'] else "N/A"
            do = f"{st['do_avg']:.1f}" if st['do_avg'] else "N/A"
            temp = f"{st['temp_avg']:.1f}" if st['temp_avg'] else "N/A"
            tn = f"{st['tn_avg']:.3f}" if st['tn_avg'] else "N/A"
            tp = f"{st['tp_avg']:.4f}" if st['tp_avg'] else "N/A"
            md += f"| {st['station']} | {st['count']} | {ph} | {do} | {temp} | {tn} | {tp} | {st['dominant_grade']} |\n"

        if wq["do_alert"]:
            md += "\n> DO 5.0mg/L 미만 관측 — 수질 개선 주의\n"
        if wq["ph_alert"]:
            md += "\n> pH 정상범위 이탈 — 오염원 점검 필요\n"
    else:
        md += "수질 데이터 축적 중.\n"

    md += "\n---\n\n## 4. 생물다양성 현황\n\n"
    if sp:
        md += f"- 총 **{sp['total_species']}종** 관찰 ({sp['total_observations']}건)\n"
        md += f"- 외래종 **{sp['invasive_count']}건** 감지\n\n"

        if sp.get("top_species"):
            md += "### 다빈도 관찰 종\n\n| 종명 | 관찰 수 |\n|------|--------|\n"
            for name, count in sp["top_species"]:
                md += f"| {name} | {count} |\n"
            md += "\n"

        if sp.get("river_diversity"):
            md += "### 하천별 다양성\n\n| 하천 | 관찰 종수 |\n|------|----------|\n"
            for rd in sp["river_diversity"][:10]:
                md += f"| {rd['river']} | {rd['species_count']} |\n"
    else:
        md += "생물 관찰 데이터 축적 필요.\n"

    md += "\n---\n\n## 5. 수위 위험 현황\n\n"
    if lv:
        md += f"- 총 {lv['stations']}개 관측소 모니터링\n"
        md += f"- 위험: {lv['danger_count']}개소, 주의: {lv['warning_count']}개소\n\n"
        if lv.get("danger_stations"):
            md += "| 관측소 | 하천 | 수위비율 |\n|--------|------|----------|\n"
            for d in lv["danger_stations"]:
                md += f"| {d['station']} | {d['river']} | {d['level_ratio']}% |\n"
    else:
        md += "수위 데이터 없음.\n"

    md += "\n---\n\n## 6. 외래종 경보\n\n"
    if alerts:
        md += "| 종명 | 하천 | 경보 | 감지일 |\n|------|------|------|--------|\n"
        for a in alerts:
            level_kr = {"critical": "긴급", "warning": "주의", "info": "관찰"}.get(a["level"], "?")
            md += f"| {a['species']} | {a['river']} | {level_kr} | {a['date']} |\n"
    else:
        md += "현재 외래종 경보 없음.\n"

    md += "\n---\n\n## 7. 기상 연계 분석\n\n"
    if wx:
        md += f"- 강수 위험일: {wx['rain_risk_days']}일\n"
        if wx['avg_high']:
            md += f"- 평균 최고기온: {wx['avg_high']}도\n"
        if wx['avg_low']:
            md += f"- 평균 최저기온: {wx['avg_low']}도\n"
    else:
        md += "기상 데이터 없음.\n"

    md += "\n---\n\n## 8. 정책 제언\n\n"
    for r in recs:
        priority_emoji = {"긴급": "🔴", "주의": "🟡", "양호": "🟢"}.get(r["priority"], "")
        md += f"- {priority_emoji} **[{r['priority']}]** {r['text']}\n"

    md += f"""
---

## 데이터 출처

- 수위: 서울시 열린데이터 API
- 생물: iNaturalist API + 시민 제보
- EHI: RiverWatch 생태건강지수 모델
- 수질 TMS: 서울시 하천수질자동측정 (WPOSInformationTime)
- 기상: 기상청 단기예보 API
- 외래종: 환경부 생태교란종 DB

---

*이 보고서는 RiverWatch Auto Report v2에 의해 자동 생성되었습니다.*
*도깨비3.0 팀 (AI활동가 1기)*
"""
    return md


def generate_report():
    now = datetime.now()
    month_str = now.strftime("%Y-%m")
    date_str = now.strftime("%Y-%m-%d %H:%M")

    print("  [1/6] EHI 데이터 조회...")
    ehi_data = supabase_get("ehi_scores", "select=*&order=created_at.desc&limit=100")

    print("  [2/6] 생물 관찰 조회...")
    species_data = supabase_get("species_observations", "select=*&order=observed_at.desc&limit=1000")

    print("  [3/6] 수위 데이터 조회...")
    readings = supabase_get("river_readings", "select=*&order=id.desc&limit=500")

    print("  [4/6] 수질 TMS 조회...")
    wq_data = supabase_get("water_quality", "select=*&order=collected_at.desc&limit=500")

    print("  [5/6] 기상 예보 조회...")
    weather_data = supabase_get("weather_forecasts", "select=*&order=created_at.desc&limit=50")

    print("  [6/6] 외래종 경보 조회...")
    alerts = supabase_get("invasive_alerts", "select=*&order=created_at.desc&limit=50")

    print("\n  분석 시작...")
    ehi_analysis = analyze_ehi(ehi_data)
    species_analysis = analyze_species(species_data)
    level_analysis = analyze_water_level(readings)
    wq_analysis = analyze_water_quality(wq_data)
    weather_analysis = analyze_weather(weather_data)
    recommendations = generate_policy_recommendations(ehi_analysis, wq_analysis, species_analysis, level_analysis)

    report_json = {
        "meta": {
            "title": f"서울 하천 생태 종합 분석 보고서 — {month_str}",
            "generated_at": date_str,
            "generator": "RiverWatch Auto Report v2",
            "period": month_str,
        },
        "summary": {
            "rivers_monitored": ehi_analysis["river_count"] if ehi_analysis else 0,
            "avg_ehi": ehi_analysis["avg_ehi"] if ehi_analysis else 0,
            "total_species": species_analysis["total_species"] if species_analysis else 0,
            "total_observations": species_analysis["total_observations"] if species_analysis else 0,
            "invasive_count": species_analysis["invasive_count"] if species_analysis else 0,
            "danger_stations": level_analysis["danger_count"] if level_analysis else 0,
            "wq_stations": len(wq_analysis["stations"]) if wq_analysis else 0,
            "wq_avg_do": wq_analysis["avg_do"] if wq_analysis else None,
        },
        "ehi": ehi_analysis,
        "water_quality": wq_analysis,
        "species": species_analysis,
        "water_level": level_analysis,
        "weather": weather_analysis,
        "alerts": [
            {
                "species": a.get("species_name", ""),
                "river": a.get("river", ""),
                "level": a.get("alert_level", ""),
                "date": a.get("created_at", "")[:10],
            }
            for a in alerts[:10]
        ],
        "recommendations": recommendations,
    }

    md_report = render_markdown(report_json)

    return report_json, md_report, month_str


def main():
    load_env()

    print("=" * 60)
    print("  RiverWatch 종합 분석 보고서 생성")
    print(f"  생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    report_json, md_report, month_str = generate_report()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    json_path = os.path.join(REPORTS_DIR, f"analysis_{month_str}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_json, f, ensure_ascii=False, indent=2)
    print(f"\n  JSON 저장: {json_path}")

    md_path = os.path.join(REPORTS_DIR, f"analysis_{month_str}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"  Markdown 저장: {md_path}")

    latest_path = os.path.join(REPORTS_DIR, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(report_json, f, ensure_ascii=False, indent=2)
    print(f"  최신 보고서 링크: {latest_path}")

    summary = report_json.get("summary", {})
    print(f"\n  --- 요약 ---")
    print(f"  하천: {summary.get('rivers_monitored', 0)}개")
    print(f"  평균 EHI: {summary.get('avg_ehi', 0)}점")
    print(f"  종 수: {summary.get('total_species', 0)}종")
    print(f"  관찰: {summary.get('total_observations', 0)}건")
    print(f"  외래종: {summary.get('invasive_count', 0)}건")
    print(f"  위험: {summary.get('danger_stations', 0)}개소")
    print(f"  수질 DO: {summary.get('wq_avg_do', 'N/A')} mg/L")

    recs = report_json.get("recommendations", [])
    if recs:
        print(f"\n  --- 정책 제언 ({len(recs)}건) ---")
        for r in recs:
            print(f"  [{r['priority']}] {r['text']}")

    print(f"\n  보고서 생성 완료")


if __name__ == "__main__":
    main()

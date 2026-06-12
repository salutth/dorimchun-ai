"""
외래종 경보 Agent (RiverWatch Agent 3)
- 입력: Supabase species_observations에서 is_invasive=true 레코드
- 처리: 미알림 외래종 관찰 → invasive_alerts 테이블 저장 + 경보 출력
- 출력: 외래종 감지 현황 + 경보 발송 (터미널 + Supabase)
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INVASIVE_DB = {
    "Trachemys scripta": {"korean": "붉은귀거북", "risk": "high", "action": "포획 신고 (환경청)"},
    "Micropterus salmoides": {"korean": "배스", "risk": "high", "action": "포획 권고"},
    "Lepomis macrochirus": {"korean": "블루길", "risk": "high", "action": "포획 권고"},
    "Myocastor coypus": {"korean": "뉴트리아", "risk": "high", "action": "즉시 신고 (지자체)"},
    "Lithobates catesbeianus": {"korean": "황소개구리", "risk": "high", "action": "포획 신고"},
    "Rana catesbeiana": {"korean": "황소개구리", "risk": "high", "action": "포획 신고"},
    "Procambarus clarkii": {"korean": "미국가재", "risk": "high", "action": "포획 신고"},
    "Ambrosia artemisiifolia": {"korean": "돼지풀", "risk": "medium", "action": "제거 권고"},
    "Solidago altissima": {"korean": "양미역취", "risk": "medium", "action": "제거 권고"},
    "Humulus japonicus": {"korean": "환삼덩굴", "risk": "medium", "action": "제거 권고"},
    "Rumex acetosella": {"korean": "애기수영", "risk": "low", "action": "모니터링"},
    "Ageratina altissima": {"korean": "서양등골나물", "risk": "medium", "action": "제거 권고"},
    "Paspalum distichum": {"korean": "물참새피", "risk": "medium", "action": "제거 권고"},
    "Alternanthera philoxeroides": {"korean": "악어풀", "risk": "high", "action": "즉시 제거"},
    "Ludwigia grandiflora": {"korean": "큰꽃물달개비", "risk": "high", "action": "즉시 제거"},
}

RISK_ICON = {"high": "\U0001f6a8", "medium": "⚠️", "low": "\U0001f50d"}
RISK_LABEL = {"high": "긴급", "medium": "주의", "low": "관찰"}


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

    url = f"{url_base}/rest/v1/{table}"
    payload = json.dumps(records).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
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
    print("  외래종 경보 시스템 — RiverWatch Agent 3")
    print(f"  점검 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    invasive_obs = supabase_get("species_observations",
        "select=id,taxon_name,river,latitude,longitude,observed_at,observer"
        "&is_invasive=eq.true&order=observed_at.desc&limit=100")

    existing_alerts = supabase_get("invasive_alerts",
        "select=observation_id&limit=500")
    alerted_ids = set(a.get("observation_id") for a in existing_alerts if a.get("observation_id"))

    all_species = supabase_get("species_observations",
        "select=taxon_name,river,is_invasive&limit=500")

    total_obs = len(all_species)
    total_invasive = sum(1 for s in all_species if s.get("is_invasive"))

    print(f"\n  전체 관찰: {total_obs}건 | 외래종: {total_invasive}건 "
          f"| 외래종 비율: {total_invasive/total_obs*100:.1f}%" if total_obs else "\n  관찰 데이터 없음")

    if not invasive_obs:
        print("\n  ✅ 외래종 미감지 — 현재 경보 없음")
        print()
        return

    print(f"\n  {'종명':<28} {'한국명':<10} {'하천':<8} {'위험도':<6} {'관찰일':<12} {'조치'}")
    print("  " + "-" * 80)

    new_alerts = []

    for obs in invasive_obs:
        taxon = obs.get("taxon_name", "")
        info = INVASIVE_DB.get(taxon, {"korean": "미등록 외래종", "risk": "medium", "action": "확인 필요"})
        river = obs.get("river", "")
        observed = obs.get("observed_at", "")[:10]
        risk = info["risk"]
        icon = RISK_ICON.get(risk, "")
        label = RISK_LABEL.get(risk, "")

        is_new = obs.get("id") not in alerted_ids
        new_marker = " [NEW]" if is_new else ""

        print(f"  {taxon:<28} {info['korean']:<10} {river:<8} {icon} {label:<4} {observed:<12} {info['action']}{new_marker}")

        if is_new and obs.get("id"):
            alert_level = "critical" if risk == "high" else "warning" if risk == "medium" else "info"
            new_alerts.append({
                "observation_id": obs["id"],
                "species_name": taxon,
                "alert_level": alert_level,
                "river": river,
                "latitude": obs.get("latitude"),
                "longitude": obs.get("longitude"),
            })

    if new_alerts:
        print(f"\n  \U0001f6a8 신규 경보: {len(new_alerts)}건")
        saved = supabase_post("invasive_alerts", new_alerts)
        if saved:
            print(f"  \U0001f4be Supabase 경보 저장: {saved}건")

        for alert in new_alerts:
            info = INVASIVE_DB.get(alert["species_name"], {})
            if info.get("risk") == "high":
                print(f"\n  \U0001f6a8\U0001f6a8\U0001f6a8 긴급 경보 \U0001f6a8\U0001f6a8\U0001f6a8")
                print(f"  종: {alert['species_name']} ({info.get('korean', '')})")
                print(f"  하천: {alert['river']}")
                print(f"  조치: {info.get('action', '')}")
                print(f"  → 환경청 생태교란종 신고: 1899-5765")
    else:
        print("\n  ✅ 신규 외래종 경보 없음 (기존 건 모두 처리됨)")

    print()


if __name__ == "__main__":
    main()

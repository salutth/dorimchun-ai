"""
수질 TMS 데이터 수집 Agent (RiverWatch Phase 2)
- 입력: 서울시 열린데이터 하천 수질 API (ListWQMSService)
- 처리: pH, DO(용존산소), BOD, COD, SS, 수온 등 수질 항목 수집
- 출력: Supabase water_quality 테이블 저장
"""

import json
import os
import ssl
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


def fetch_water_quality(api_key):
    url = f"http://openAPI.seoul.go.kr:8088/{api_key}/json/WPOSInformationTime/1/100/"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_float(val):
    try:
        return round(float(val), 2) if val and val.strip() else None
    except (ValueError, TypeError):
        return None


GRADE_THRESHOLDS = {
    "do": [(7.5, "매우좋음"), (5.0, "좋음"), (2.0, "보통"), (0, "나쁨")],
    "bod": [(1.0, "매우좋음"), (3.0, "좋음"), (6.0, "보통"), (999, "나쁨")],
    "ph": [(8.5, "적정"), (6.5, "적정")],
}


def grade_do(val):
    if val is None:
        return "측정불가"
    for threshold, grade in GRADE_THRESHOLDS["do"]:
        if val >= threshold:
            return grade
    return "매우나쁨"


def grade_bod(val):
    if val is None:
        return "측정불가"
    for threshold, grade in GRADE_THRESHOLDS["bod"]:
        if val <= threshold:
            return grade
    return "매우나쁨"


def save_to_supabase(records):
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not sb_url or not sb_key:
        print("  ⚠ Supabase 미설정")
        return

    body = json.dumps(records, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{sb_url}/rest/v1/water_quality",
        data=body,
        method="POST",
        headers={
            "apikey": sb_key,
            "Authorization": f"Bearer {sb_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            print(f"  ✅ Supabase 저장: {resp.status} ({len(records)}건)")
    except Exception as e:
        print(f"  ❌ Supabase 오류: {e}")


def report_health(status, message, count=0):
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not sb_url or not sb_key:
        return
    body = json.dumps({
        "collector": "water_quality",
        "status": status,
        "message": message,
        "records_count": count,
        "collected_at": datetime.utcnow().isoformat() + "Z",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{sb_url}/rest/v1/collector_health",
        data=body,
        method="POST",
        headers={
            "apikey": sb_key,
            "Authorization": f"Bearer {sb_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        urllib.request.urlopen(req, timeout=10, context=ctx)
    except Exception:
        pass


def main():
    print("=" * 50)
    print("💧 수질 TMS 데이터 수집 시작")
    print("=" * 50)

    load_env()
    api_key = os.environ.get("SEOUL_API_KEY", "")
    if not api_key:
        print("❌ SEOUL_API_KEY 없음")
        report_health("error", "API 키 없음")
        return

    try:
        data = fetch_water_quality(api_key)
    except Exception as e:
        print(f"❌ API 호출 실패: {e}")
        report_health("error", str(e))
        return

    service = data.get("WPOSInformationTime", {})
    result = service.get("RESULT", {})
    if result.get("CODE") != "INFO-000":
        msg = result.get("MESSAGE", "알 수 없는 오류")
        print(f"❌ API 오류: {msg}")
        report_health("error", msg)
        return

    rows = service.get("row", [])
    print(f"📊 수질 데이터 {len(rows)}건 수신")

    records = []
    for r in rows:
        ph = parse_float(r.get("TOT_PH"))
        do_val = parse_float(r.get("TOT_DO"))
        temp = parse_float(r.get("WATT"))
        tn = parse_float(r.get("TOT_N"))
        tp = parse_float(r.get("TOT_TP"))
        toc = parse_float(r.get("TOT_OC"))
        phnl = parse_float(r.get("PHNL"))
        cn = parse_float(r.get("CN"))

        ymd = r.get("YMD", "")
        hr = r.get("HR", "00:00")
        measured = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}T{hr}:00" if len(ymd) == 8 else datetime.now(tz=None).isoformat()

        record = {
            "station_name": r.get("MSRSTN_NM", ""),
            "ph": ph,
            "dissolved_oxygen": do_val,
            "water_temp": temp,
            "total_nitrogen": tn,
            "total_phosphorus": tp,
            "toc": toc,
            "phenol": phnl,
            "cyanide": cn,
            "do_grade": grade_do(do_val),
            "measured_at": measured,
            "collected_at": datetime.now(tz=None).isoformat() + "Z",
        }
        records.append(record)

        do_str = f"DO={do_val}" if do_val else "DO=N/A"
        ph_str = f"pH={ph}" if ph else "pH=N/A"
        print(f"  📍 {record['station_name']}: {ph_str}, {do_str}, 수온={temp}°C")

    if records:
        save_to_supabase(records)
        report_health("ok", f"{len(records)}건 수집 완료", len(records))
    else:
        print("⚠ 수집된 데이터 없음")
        report_health("warning", "데이터 없음")

    print(f"\n✅ 수질 TMS 수집 완료: {len(records)}건")


if __name__ == "__main__":
    main()

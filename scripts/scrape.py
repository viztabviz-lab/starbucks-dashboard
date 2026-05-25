"""
스타벅스 코리아 전국 매장 데이터 수집 스크립트
================================================
실행: python scripts/scrape.py
출력: data/stores.json
"""

import requests
import json
import time
import os
from datetime import datetime, timezone, timedelta

# ── 상수 ──────────────────────────────────────────────────────────────────────

KST = timezone(timedelta(hours=9))

SIDO_CODES = {
    "서울": "01", "경기": "02", "인천": "03", "강원": "04",
    "충북": "05", "충남": "06", "대전": "07", "경북": "08",
    "경남": "09", "부산": "10", "울산": "11", "대구": "12",
    "전북": "13", "전남": "14", "광주": "15", "제주": "16", "세종": "17",
}

SIDO_CENTERS = {
    "서울": ("37.5665", "126.9780"), "경기": ("37.4138", "127.5183"),
    "인천": ("37.4563", "126.7052"), "강원": ("37.8228", "128.1555"),
    "충북": ("36.6357", "127.4912"), "충남": ("36.5184", "126.8000"),
    "대전": ("36.3504", "127.3845"), "경북": ("36.4919", "128.8889"),
    "경남": ("35.4606", "128.2132"), "부산": ("35.1796", "129.0756"),
    "울산": ("35.5384", "129.3114"), "대구": ("35.8714", "128.6014"),
    "전북": ("35.8202", "127.1089"), "전남": ("34.8679", "126.9910"),
    "광주": ("35.1595", "126.8526"), "제주": ("33.4996", "126.5312"),
    "세종": ("36.4801", "127.2890"),
}

# 현재 활성 API 엔드포인트 (두 가지 시도)
API_ENDPOINTS = [
    "https://www.starbucks.co.kr/store/getStoreListJson.do",
    "https://www.istarbucks.co.kr/store/getStore.do",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.starbucks.co.kr/store/store_map.do?disp=locale",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# ── 수집 함수 ──────────────────────────────────────────────────────────────────

def fetch_sido(sido_name: str, sido_cd: str, lat: str, lng: str, api_url: str) -> list:
    """단일 시/도 매장 목록 수집."""
    payload = {
        "ins_lat": lat,
        "ins_lng": lng,
        "p_sido_cd": sido_cd,
        "p_gugun_cd": "",
        "in_biz_cd": "",
        "set_date": "",
        "iend": "2000",
    }
    res = requests.post(api_url, data=payload, headers=HEADERS, timeout=20)
    res.raise_for_status()
    raw = res.json()
    stores = raw.get("list", raw.get("stores", []))
    result = []
    for s in stores:
        name    = s.get("s_name", s.get("name", "")).strip()
        address = s.get("address", s.get("addr", "")).strip()
        lat_v   = s.get("lat", s.get("latitude", ""))
        lng_v   = s.get("lot", s.get("longitude", s.get("lng", "")))
        if not name or not lat_v or not lng_v:
            continue
        is_dt = "DT" in name or "드라이브" in name
        is_rv = name.endswith(" R") or "리저브" in name
        result.append({
            "r":   sido_name,
            "n":   name,
            "a":   address.replace(" 1522-3232", ""),
            "lat": round(float(lat_v), 5),
            "lng": round(float(lng_v), 5),
            "dt":  1 if is_dt else 0,
            "rv":  1 if is_rv else 0,
        })
    return result


def collect_all() -> list:
    """전체 시/도 순회하여 매장 목록 수집. 실패 시 다른 엔드포인트로 재시도."""
    all_stores = []
    active_url = None

    # 사용 가능한 API 엔드포인트 탐지
    test_sido = "서울"
    test_cd   = SIDO_CODES[test_sido]
    test_lat, test_lng = SIDO_CENTERS[test_sido]

    for url in API_ENDPOINTS:
        try:
            result = fetch_sido(test_sido, test_cd, test_lat, test_lng, url)
            if result:
                active_url = url
                all_stores.extend(result)
                print(f"✅ API 엔드포인트 확인: {url}")
                print(f"   {test_sido}: {len(result)}개")
                break
        except Exception as e:
            print(f"⚠️  {url} 실패: {e}")

    if not active_url:
        raise RuntimeError("❌ 모든 API 엔드포인트 접근 실패. 스타벅스 API 구조 변경 여부를 확인하세요.")

    # 나머지 시/도 수집
    for sido_name, sido_cd in SIDO_CODES.items():
        if sido_name == test_sido:
            continue
        lat, lng = SIDO_CENTERS[sido_name]
        try:
            stores = fetch_sido(sido_name, sido_cd, lat, lng, active_url)
            print(f"   {sido_name}: {len(stores)}개")
            all_stores.extend(stores)
        except Exception as e:
            print(f"   ⚠️  {sido_name} 수집 실패: {e}")
        time.sleep(0.4)

    return all_stores


# ── 집계 ───────────────────────────────────────────────────────────────────────

def build_summary(stores: list) -> dict:
    """지역별·유형별 집계."""
    region_stats = {}
    gu_count     = {}

    for s in stores:
        r = s["r"]
        if r not in region_stats:
            region_stats[r] = {"total": 0, "dt": 0, "rv": 0}
        region_stats[r]["total"] += 1
        region_stats[r]["dt"]    += s["dt"]
        region_stats[r]["rv"]    += s["rv"]

        parts = s["a"].split()
        if len(parts) >= 2:
            gu = parts[1]
            gu_count[gu] = gu_count.get(gu, 0) + 1

    top_gu = sorted(gu_count.items(), key=lambda x: -x[1])[:15]
    return {"region_stats": region_stats, "top_gu": top_gu}


# ── 저장 ───────────────────────────────────────────────────────────────────────

def save(stores: list, summary: dict):
    os.makedirs("data", exist_ok=True)
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    payload = {
        "updated":      now_kst,
        "total":        len(stores),
        "dt_count":     sum(s["dt"] for s in stores),
        "rv_count":     sum(s["rv"] for s in stores),
        "region_stats": summary["region_stats"],
        "top_gu":       summary["top_gu"],
        "stores":       stores,
    }

    with open("data/stores.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize("data/stores.json") / 1024
    print(f"\n✅ data/stores.json 저장 완료")
    print(f"   총 매장: {len(stores):,}개 | 파일 크기: {size_kb:.1f} KB")
    print(f"   업데이트: {now_kst}")


# ── 메인 ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  스타벅스 코리아 전국 매장 데이터 수집")
    print("=" * 55)
    stores  = collect_all()
    summary = build_summary(stores)
    save(stores, summary)

# redev_manager.py — 서울시 정비사업(재개발/재건축) 현황 수집 → 지도 레이어용 JSON 생성
#
# 데이터: 서울 열린데이터광장 TbSeoulRedevStatus (분기 갱신, 472개 구역)
# 인증키: keyring.set_password('seoul_data', 'api_key', '발급키')  (1회)
# 좌표: 기존 카카오 지오코딩 캐시(GeoCache) 재사용
# 출력: data/redev_zones.json
#
# 실행: python redev_manager.py

import json
import sys
import keyring
import requests
from pathlib import Path
from geo_cache import GeoCache

ROOT_DIR = Path(__file__).parent
BASE_DIR = ROOT_DIR / "data"
CACHE_PATH = BASE_DIR / "address_cache.json"
OUT_PATH = BASE_DIR / "redev_zones.json"

SEOUL_KEY = keyring.get_password("seoul_data", "api_key")
KAKAO_KEY = keyring.get_password("kakao", "api_key")

if not SEOUL_KEY:
    print("(!) 서울 열린데이터광장 인증키가 없습니다.")
    print("    python -c \"import keyring; keyring.set_password('seoul_data','api_key','발급키')\"")
    sys.exit(1)


def fetch_all_zones() -> list[dict]:
    """TbSeoulRedevStatus 전체 행 수집 (1000건 단위 페이징)"""
    rows, start = [], 1
    while True:
        end = start + 999
        url = f"http://openapi.seoul.go.kr:8088/{SEOUL_KEY}/json/TbSeoulRedevStatus/{start}/{end}/"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        svc = data.get("TbSeoulRedevStatus")
        if not svc:
            # 인증 오류 등은 RESULT 루트로 옴
            msg = (data.get("RESULT") or {}).get("MESSAGE", "unknown")
            raise RuntimeError(f"API 오류: {msg}")
        total = int(svc.get("list_total_count", 0))
        batch = svc.get("row", [])
        rows.extend(batch)
        if len(rows) >= total or not batch:
            break
        start = end + 1
    return rows


def clean_jibun(addr: str) -> str:
    """지번주소 정리: '일대', '일원', '외 N필지' 등 접미어 제거"""
    if not addr or addr.strip() in ("-", ""):
        return ""
    s = addr.strip()
    for suffix in ("일대", "일원", "번지"):
        s = s.replace(suffix, " ")
    # '외 3필지' 류 제거
    if " 외" in s:
        s = s.split(" 외")[0]
    return " ".join(s.split())


def main():
    print("[정비사업 데이터 수집 시작]")
    zones = fetch_all_zones()
    print(f"  > {len(zones)}개 구역 수신")

    geo = GeoCache(CACHE_PATH, KAKAO_KEY)

    out, fail = [], 0
    for z in zones:
        district = (z.get("DISTRICT") or "").strip()
        jibun = clean_jibun(z.get("JIBUN_ADDR") or "")
        road = (z.get("ROAD_ADDR") or "").strip()

        coords = None
        # 1순위: 지번주소, 2순위: 도로명, 3순위: 동 단위, 4순위: 구 단위
        if jibun:
            coords = geo.get_coords(f"서울특별시 {district} {jibun}")
        if not coords and road and road != "-":
            coords = geo.get_coords(f"서울특별시 {district} {road}")
        if not coords and jibun:
            dong = jibun.split()[0] if jibun.split() else ""
            if dong:
                coords = geo.get_coords(f"서울특별시 {district} {dong}")
        if not coords:
            coords = geo.get_coords(f"서울특별시 {district}")
        if not coords:
            fail += 1
            continue

        out.append({
            "name": (z.get("ZONE_NM") or "").strip(),
            "district": district,
            "addr": (z.get("JIBUN_ADDR") or "").strip(),
            "type": (z.get("BIZ_TYPE") or "").strip(),
            "stage": (z.get("BIZ_STAGE") or "").strip(),
            "coords": coords,
            "hh_exist": z.get("EXISTING_HOUSEHOLDS") or "",
            "hh_total": z.get("TOT_BUILT_HOUSEHOLDS") or "",
            "hh_sale": z.get("SALE_BUILT_HOUSEHOLDS") or "",
            "hh_rent": z.get("RENT_BUILT_HOUSEHOLDS") or "",
            "d_zone": z.get("ZONE_DESIGNATION_INIT_YMD") or "",
            "d_committee": z.get("PROMOTION_COMMITTEE_YMD") or "",
            "d_assoc": z.get("ASSOCIATION_ESTABLISHMENT_YMD") or "",
            "d_impl": z.get("BIZ_IMPLEMENTATION_INIT_YMD") or "",
            "d_mgmt": z.get("MGMT_DISPOSITION_INIT_YMD") or "",
            "d_constr": z.get("CONSTRUCTION_START_YMD") or "",
        })

    geo.save()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f"[완료] {len(out)}개 구역 저장 (지오코딩 실패 {fail}건) → {OUT_PATH}")

    # 단계 분포 출력 (색상 매핑 참고용)
    from collections import Counter
    for stage, n in Counter(z['stage'] for z in out).most_common():
        print(f"    {stage or '(공란)'}: {n}")


if __name__ == "__main__":
    main()

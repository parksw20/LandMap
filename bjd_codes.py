# bjd_codes.py — 실거래 데이터에 등장하는 모든 법정동의 코드 수집
#
# 배경: 주택인허가 API는 sigunguCd + bjdongCd(법정동코드)를 둘 다 요구한다.
#       기존에는 K-apt 목록의 bjdCode만 써서 814개 동만 수집했는데,
#       실제 우리 데이터에는 1,341개 동이 있어 공급면적 커버리지가 낮았다.
#
# 방법: 동 중심 좌표(지오코딩 캐시)로 VWorld 연속지적도를 찍으면 필지의 PNU가 오고,
#       PNU 앞 10자리가 곧 법정동코드다.
#
# 실행: python bjd_codes.py   → data/hspms_cache/bjd_map.json 갱신(합집합)

import json
import glob
import time
from pathlib import Path

import keyring
import requests

from geo_cache import GeoCache

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = DATA / "hspms_cache" / "bjd_map.json"
ADDR_CACHE = DATA / "address_cache.json"

VW_KEY = keyring.get_password("v-world", "parksw20")
H = {"Referer": "http://localhost:8080"}


def all_dongs():
    """실거래 데이터에 등장하는 법정동 전체 (주거·업무 유형 기준)"""
    names = set()
    for t in ("apt", "rh", "off", "silv", "sh"):
        for f in glob.glob(str(DATA / "hierarchy" / "*" / t / "summary_dong.json")):
            try:
                for x in json.loads(Path(f).read_text(encoding="utf-8")):
                    if x.get("name"):
                        names.add(x["name"])
            except Exception:
                continue
    return sorted(names)


def pnu_at(lng, lat):
    """좌표의 필지 PNU (앞 10자리 = 법정동코드)"""
    try:
        r = requests.get("https://api.vworld.kr/req/data",
                         params={"service": "data", "request": "GetFeature",
                                 "data": "LP_PA_CBND_BUBUN", "key": VW_KEY,
                                 "geomFilter": f"POINT({lng} {lat})", "size": "1",
                                 "format": "json", "crs": "EPSG:4326", "domain": "localhost"},
                         headers=H, timeout=20)
        d = r.json()["response"]
        if d["status"] != "OK":
            return None
        p = d["result"]["featureCollection"]["features"][0]["properties"]
        pnu = (p.get("pnu") or "").strip()
        return pnu[:10] if len(pnu) >= 10 else None
    except Exception:
        return None


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    have = set(json.loads(OUT.read_text(encoding="utf-8"))) if OUT.exists() else set()
    print(f"[i] 기존 법정동코드 {len(have)}개")

    geo = GeoCache(ADDR_CACHE, keyring.get_password("kakao", "api_key"))
    dongs = all_dongs()
    print(f"[i] 실거래 법정동 {len(dongs)}개 — 코드 확보 시도")

    added = fail = 0
    try:
        for i, name in enumerate(dongs, 1):
            c = geo.get_coords(name)
            if not c:
                fail += 1
                continue
            code = pnu_at(c[0], c[1])
            if code and code not in have:
                have.add(code)
                added += 1
            elif not code:
                fail += 1
            if i % 100 == 0:
                OUT.write_text(json.dumps(sorted(have)), encoding="utf-8")
                print(f"  진행 {i}/{len(dongs)} | 누적 {len(have)} (신규 {added}, 실패 {fail})")
            time.sleep(0.03)
    except KeyboardInterrupt:
        print("[!] 중단 — 진행분 저장")
    finally:
        OUT.write_text(json.dumps(sorted(have)), encoding="utf-8")
        geo.save()
    print(f"[완료] 법정동코드 {len(have)}개 (신규 {added}, 좌표/조회 실패 {fail})")


if __name__ == "__main__":
    main()

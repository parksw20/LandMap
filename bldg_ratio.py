# bldg_ratio.py — 아파트 단지별 용적률·건폐율 수집 → data/bldg_ratio.json
#
# 배경: 용적률·건폐율은 브라우저가 단지를 클릭할 때마다 VWorld에 직접 조회했다.
#       준공 후에는 바뀌지 않는 값이므로 한 번 받아 저장해 두고, 재수집은
#       '건축년도가 달라졌을 때'(재건축·신축으로 건물이 바뀐 경우)만 한다.
#
# 매칭 규칙(프론트엔드와 동일):
#   1) 단지 좌표의 건물을 점 조회 → 용적률/건폐율이 있으면 채택
#   2) 없으면 주변 ±50m 박스에서 '공동주택 + 건축년도 ±1년'인 건물만 후보로 삼아
#      가장 큰 건물을 채택 (이웃 건물 값이 섞이는 것을 막기 위함)
#
# 실행: python bldg_ratio.py            # 신규/건축년도 변경분만
#       python bldg_ratio.py --refresh  # 전체 재수집

import json
import glob
import sys
import time
from collections import Counter
from pathlib import Path

import keyring
import requests

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = DATA / "bldg_ratio.json"

VW_KEY = keyring.get_password("v-world", "parksw20")
if not VW_KEY or len(VW_KEY) < 10:
    print("(!) VWorld 키 없음"); sys.exit(1)
H = {"Referer": "http://localhost:8080"}

TYPES = ["apt", "off", "silv"]   # 연립/다세대는 단지 수가 11만이라 제외
req_count = 0


class QuotaExceeded(Exception):
    pass


def vw(params, retries=3):
    global req_count
    for i in range(retries):
        try:
            r = requests.get("https://api.vworld.kr/req/data",
                             params={**params, "service": "data", "request": "GetFeature",
                                     "key": VW_KEY, "format": "json", "crs": "EPSG:4326",
                                     "domain": "localhost"},
                             headers=H, timeout=25)
            req_count += 1
            d = r.json()["response"]
            if d["status"] == "OK":
                return d["result"]["featureCollection"]["features"]
            if d["status"] == "NOT_FOUND":
                return []
            err = str(d.get("error", {})).upper()
            if "LIMIT" in err or "QUOTA" in err:
                raise QuotaExceeded(str(d.get("error")))
            return []
        except QuotaExceeded:
            raise
        except Exception:
            time.sleep(1 + i)
    return []


def num(v):
    try:
        x = float(v)
        return round(x, 2) if x > 0 else 0
    except (TypeError, ValueError):
        return 0


def fetch_ratio(lng, lat, build_year):
    """(용적률, 건폐율) — 못 찾으면 (0, 0)"""
    # 1) 점 조회: 좌표가 건물 안이면 가장 정확하다
    for f in vw({"data": "LT_C_BLDGINFO", "geomFilter": f"POINT({lng} {lat})", "size": "1"}):
        p = f["properties"]
        if num(p.get("vl_rat")) or num(p.get("bc_rat")):
            return num(p.get("vl_rat")), num(p.get("bc_rat"))
    # 2) 좌표가 건물 밖(도로·공지)인 경우 — 주변에서 '이 단지의 건물'만 찾는다
    if not build_year:
        return 0, 0
    d = 0.0006
    best = None
    for f in vw({"data": "LT_C_BLDGINFO",
                 "geomFilter": f"BOX({lng-d},{lat-d},{lng+d},{lat+d})", "size": "50"}):
        p = f["properties"]
        ap = (p.get("useapr_day") or "")[:4]
        if p.get("usability") != "02000" or not ap.isdigit():
            continue
        if abs(int(ap) - build_year) > 1:
            continue
        vl, bc = num(p.get("vl_rat")), num(p.get("bc_rat"))
        if not vl and not bc:
            continue
        area = num(p.get("totalarea"))
        if not best or area > best[0]:
            best = (area, vl, bc)
    return (best[1], best[2]) if best else (0, 0)


def load_targets():
    """(단지명|주소) → (경도, 위도, 대표 건축년도) — 유형 무관 합집합"""
    out = {}
    for t in TYPES:
        for f in glob.glob(str(DATA / "hierarchy" / "*" / t / "details" / "*.json")):
            try:
                rows = json.loads(Path(f).read_text(encoding="utf-8"))
            except Exception:
                continue
            for x in rows:
                name, addr, coords = x.get("name"), x.get("address"), x.get("coords")
                if not name or not coords:
                    continue
                key = f"{name}|{addr}"
                years = Counter(d["by"] for d in (x.get("deals") or [])
                                if isinstance(d.get("by"), int) and d["by"] > 1900)
                by = years.most_common(1)[0][0] if years else 0
                cur = out.get(key)
                # 건축년도는 거래가 많은 쪽(최빈)을 신뢰
                if not cur or (by and not cur[2]):
                    out[key] = (coords[0], coords[1], by)
    return out


def main():
    cache = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    targets = load_targets()
    refresh = "--refresh" in sys.argv

    todo = []
    for k, (lng, lat, by) in targets.items():
        old = cache.get(k)
        # 재수집 조건: 미수집 / 건축년도가 달라짐(재건축·신축) / --refresh
        if refresh or old is None or old.get("by", 0) != by:
            todo.append((k, lng, lat, by))

    print(f"[i] 대상 단지 {len(targets):,} / 수집 필요 {len(todo):,} (기존 {len(cache):,})")

    stop = None
    got = 0
    try:
        for i, (k, lng, lat, by) in enumerate(todo, 1):
            vl, bc = fetch_ratio(lng, lat, by)
            cache[k] = {"by": by}
            if vl:
                cache[k]["vl"] = vl
            if bc:
                cache[k]["bc"] = bc
            if vl or bc:
                got += 1
            if i % 200 == 0 or i == len(todo):
                OUT.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
                               encoding="utf-8")
                print(f"  진행 {i:,}/{len(todo):,} | 값 확보 {got:,} | 요청 {req_count:,}")
            time.sleep(0.02)
    except QuotaExceeded as e:
        stop = f"VWorld 쿼터 초과: {e}"
    except KeyboardInterrupt:
        stop = "중단"
    finally:
        OUT.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")

    have = sum(1 for v in cache.values() if v.get("vl") or v.get("bc"))
    if stop:
        print(f"[!] {stop} — 진행분 저장 후 종료 (재실행 시 이어서 진행)")
    print(f"[완료] 저장 {len(cache):,}단지 중 값 보유 {have:,} ({have*100//max(1,len(cache))}%) "
          f"| API 요청 {req_count:,}건 → {OUT.name}")


if __name__ == "__main__":
    main()

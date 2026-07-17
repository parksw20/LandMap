# match_buildings.py — 마스킹된 단독/다가구 매매 매물의 실제 건물 위치 매칭
#
# 원리: 마스킹 지번('2*' = 본번 20~29) + 건축년도 + 연면적(전용면적 컬럼)을
#       VWorld 건물통합정보(LT_C_BLDGINFO)와 대조 → 유일 매칭이면 실제 지번 확정
#
# 안전장치:
#  - 동별 건물 목록 캐시(data/bldg_cache/) → 재실행 시 API 재호출 없음
#  - 매칭 결과/실패 모두 data/match_cache.json에 기록 → 중단 후 재개 가능
#  - 유일(1개) 매칭만 채택, 복수 후보는 실패 처리(동 중심 유지)
#
# 실행: python match_buildings.py

import json
import re
import sys
import time
import glob
from pathlib import Path

import keyring
import requests
import pandas as pd

from geo_cache import GeoCache

ROOT = Path(__file__).parent
DATA = ROOT / "data"
BLDG_CACHE_DIR = DATA / "bldg_cache"
MATCH_CACHE = DATA / "match_cache.json"
ADDR_CACHE = DATA / "address_cache.json"
PARCEL_CACHE = DATA / "parcel_cache.json"  # 좌표→필지 조회 캐시 (재실행 비용 절감)

VW_KEY = keyring.get_password("v-world", "parksw20")
if not VW_KEY or len(VW_KEY) < 10:
    print("(!) VWorld 키 없음"); sys.exit(1)

H = {"Referer": "http://localhost:8080"}
AREA_TOL = 1.5   # 연면적 허용 오차(㎡)
req_count = 0


def vw_get(params, retries=3):
    global req_count
    for i in range(retries):
        try:
            r = requests.get("https://api.vworld.kr/req/data",
                             params={**params, "service": "data", "request": "GetFeature",
                                     "key": VW_KEY, "format": "json", "crs": "EPSG:4326",
                                     "domain": "localhost"},
                             headers=H, timeout=30)
            req_count += 1
            d = r.json()["response"]
            if d["status"] == "OK":
                return d
            if d["status"] == "NOT_FOUND":
                return None
            err = d.get("error", {})
            if "LIMIT" in str(err).upper() or "QUOTA" in str(err).upper():
                raise RuntimeError(f"쿼터 초과: {err}")
            return None
        except RuntimeError:
            raise
        except Exception:
            time.sleep(1 + i)
    return None


def fetch_dong_buildings(center, dong_key):
    """동 중심 ±약 1km 박스의 건물 목록 (건축년도·연면적 있는 것만, 캐시)"""
    cache_f = BLDG_CACHE_DIR / f"{dong_key}.json"
    if cache_f.exists():
        return json.loads(cache_f.read_text(encoding="utf-8"))
    lng, lat = center
    box = f"BOX({lng-0.012},{lat-0.009},{lng+0.012},{lat+0.009})"
    out = []
    for page in range(1, 12):
        d = vw_get({"data": "LT_C_BLDGINFO", "geomFilter": box, "size": "1000", "page": str(page)})
        if not d:
            break
        feats = d["result"]["featureCollection"]["features"]
        for f in feats:
            p = f["properties"]
            ap = (p.get("useapr_day") or "").strip()
            # 비정상 승인일자('97 2' 등) 방어: 앞 4자리가 온전한 연도일 때만
            ym = re.match(r"^(\d{4})", ap)
            year4 = int(ym.group(1)) if ym else 0
            try:
                tot = float(p.get("totalarea") or 0)
            except ValueError:
                tot = 0
            if 1800 <= year4 <= 2100 and tot > 0:
                g = f["geometry"]["coordinates"]
                ring = g[0][0] if f["geometry"]["type"] == "MultiPolygon" else g[0]
                cx = sum(pt[0] for pt in ring) / len(ring)
                cy = sum(pt[1] for pt in ring) / len(ring)
                out.append([year4, tot, round(cx, 6), round(cy, 6)])
        if len(feats) < 1000:
            break
        time.sleep(0.05)
    BLDG_CACHE_DIR.mkdir(exist_ok=True)
    cache_f.write_text(json.dumps(out), encoding="utf-8")
    return out


_parcel_cache = json.loads(PARCEL_CACHE.read_text(encoding="utf-8")) if PARCEL_CACHE.exists() else {}

def parcel_jibun(lng, lat):
    """건물 중심점 → 필지 (동이름 포함 주소, 본번, 부번) — 디스크 캐시"""
    ck = f"{lng:.6f},{lat:.6f}"
    if ck in _parcel_cache:
        return _parcel_cache[ck]
    d = vw_get({"data": "LP_PA_CBND_BUBUN", "geomFilter": f"POINT({lng} {lat})", "size": "1"})
    if not d:
        _parcel_cache[ck] = None
        return None
    p = d["result"]["featureCollection"]["features"][0]["properties"]
    res = {
        "addr": p.get("addr", ""),
        "bonbun": (p.get("bonbun") or "").lstrip("0"),
        "bubun": (p.get("bubun") or "").lstrip("0"),
    }
    _parcel_cache[ck] = res
    return res


def masked_match(masked, bonbun, bubun):
    """마스킹 패턴('2*', '1**', '28-1*')과 본번/부번 일치 검사"""
    masked = masked.strip()
    if "-" in masked:
        mb, ms = masked.split("-", 1)
    else:
        mb, ms = masked, None

    def part_ok(pattern, value):
        if "*" not in pattern:
            return pattern == value
        prefix = pattern.rstrip("*")
        stars = len(pattern) - len(prefix)
        return len(value) == len(prefix) + stars and value.startswith(prefix)

    if not part_ok(mb, bonbun):
        return False
    if ms is not None:
        return part_ok(ms, bubun)
    # RTMS 마스킹은 부번을 통째로 생략함 ('26-30' → '2*') → 부번은 검사하지 않음
    return True


def main():
    # 0) 기존 매칭 캐시 로드 (재개)
    cache = json.loads(MATCH_CACHE.read_text(encoding="utf-8")) if MATCH_CACHE.exists() else {}
    # 동 중심 좌표: GeoCache 사용 (서브캐시 폴백 + 미스 시 카카오 지오코딩)
    geo = GeoCache(ADDR_CACHE, keyring.get_password("kakao", "api_key"))

    # 1) 전체 엑셀에서 마스킹 단독 매매 행 수집
    keys = {}  # mkey -> (sido, gungu, dong, masked, byear, area)
    files = sorted(glob.glob(str(DATA / "202*" / "실거래_*.xlsx")) + glob.glob(str(DATA / "20*" / "실거래_*.xlsx")))
    files = sorted(set(glob.glob(str(DATA / "*" / "실거래_*.xlsx"))))
    for f in files:
        try:
            df = pd.read_excel(f, sheet_name="단독다가구_매매", engine="openpyxl",
                               usecols=["시/도", "구/시", "법정동", "지번", "건축년도", "전용면적"])
        except Exception:
            continue
        for _, r in df.iterrows():
            jib = str(r.get("지번") or "")
            if "*" not in jib:
                continue
            masked = jib.split()[-1] if " " in jib else jib
            sido, gungu, dong = str(r["시/도"]).strip(), str(r["구/시"]).strip(), str(r["법정동"]).strip()
            try:
                by = int(float(r["건축년도"])); area = round(float(r["전용면적"]), 2)
            except (ValueError, TypeError):
                continue
            if by < 1900 or area <= 0 or not dong:
                continue
            mkey = f"{sido}|{gungu}|{dong}|{masked}|{by}|{area:.2f}"
            keys[mkey] = (sido, gungu, dong, masked, by, area)
    todo = {k: v for k, v in keys.items() if k not in cache}
    dongs = sorted(set((v[0], v[1], v[2]) for v in todo.values()))
    print(f"[i] 마스킹 매물 고유키 {len(keys)}개 / 미처리 {len(todo)}개 / 대상 동 {len(dongs)}개")

    # 2) 동 단위로 처리
    matched_n = 0
    try:
        for di, (sido, gungu, dong) in enumerate(dongs, 1):
            center = geo.get_coords(f"{sido} {gungu} {dong}")
            if not center:
                for mk in [k for k, v in todo.items() if (v[0], v[1], v[2]) == (sido, gungu, dong)]:
                    cache[mk] = None
                continue
            dong_key = f"{sido}_{gungu}_{dong}".replace(" ", "_").replace("/", "_")
            blds = fetch_dong_buildings(center, dong_key)

            for mk, (s, g, d, masked, by, area) in [(k, v) for k, v in todo.items() if (v[0], v[1], v[2]) == (sido, gungu, dong)]:
                cands = [b for b in blds if b[0] == by and abs(b[1] - area) <= AREA_TOL]
                # 유일성 판정은 지번패턴+동명 검사 후에 하므로 후보 상한은 여유 있게
                if not (1 <= len(cands) <= 10):
                    cache[mk] = None
                    continue
                hits = []
                for _, _, cx, cy in cands:
                    pj = parcel_jibun(cx, cy)
                    time.sleep(0.03)
                    if not pj or dong not in pj["addr"]:
                        continue
                    if masked_match(masked, pj["bonbun"], pj["bubun"]):
                        jib = pj["bonbun"] + (f"-{pj['bubun']}" if pj["bubun"] else "")
                        hits.append(jib)
                uniq = sorted(set(hits))
                cache[mk] = uniq[0] if len(uniq) == 1 else None
                if cache[mk]:
                    matched_n += 1

            if di % 20 == 0 or di == len(dongs):
                MATCH_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                PARCEL_CACHE.write_text(json.dumps(_parcel_cache, ensure_ascii=False), encoding="utf-8")
                print(f"  진행 {di}/{len(dongs)}동 | 신규매칭 {matched_n} | 요청 {req_count}")
    except RuntimeError as e:
        print(f"[!] {e} — 진행분 저장 후 종료 (재실행 시 이어서 진행)")
    finally:
        MATCH_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        PARCEL_CACHE.write_text(json.dumps(_parcel_cache, ensure_ascii=False), encoding="utf-8")

    total_matched = sum(1 for v in cache.values() if v)
    print(f"[완료] 전체 {len(cache)}키 중 매칭 {total_matched} ({total_matched*100//max(1,len(cache))}%) | API 요청 {req_count}건")


if __name__ == "__main__":
    main()

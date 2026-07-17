# match_parcels.py — 마스킹 단독/다가구 매매의 필지(연속지적도) 기반 위치 매칭 (v3)
#
# 원리: RTMS 단독 매매의 '대지면적'은 거래된 필지의 대장 면적과 사실상 동일하다.
#       연속지적도(LP_PA_CBND_BUBUN)는 전 필지를 커버하므로(건물대장 커버리지 60% 한계 우회)
#       마스킹 지번 패턴('2*' = 본번 20~29) + 필지면적 일치 → 유일하면 실제 지번 확정.
#
# match_buildings.py(건물대장 방식)가 확정한 매칭은 건드리지 않고, 실패분(None)만 재시도한다.
#
# 안전장치:
#  - 동별 필지 목록 캐시(data/parcel_dong_cache/) → 재실행 시 API 재호출 없음
#  - 결과는 동일한 data/match_cache.json에 기록 → 중단 후 재개 가능
#  - 유일(1개) 매칭만 채택, 복수 후보는 지목 '대' 우선 후에도 복수면 실패 유지
#
# 실행: python match_parcels.py

import json
import re
import sys
import time
import glob
from pathlib import Path

import keyring
import requests
import pandas as pd
from pyproj import Transformer

from match_buildings import masked_match

ROOT = Path(__file__).parent
DATA = ROOT / "data"
PDONG_CACHE_DIR = DATA / "parcel_dong_cache"
MATCH_CACHE = DATA / "match_cache.json"
ADDR_CACHE = DATA / "address_cache.json"

VW_KEY = keyring.get_password("v-world", "parksw20")
if not VW_KEY or len(VW_KEY) < 10:
    print("(!) VWorld 키 없음"); sys.exit(1)

H = {"Referer": "http://localhost:8080"}
req_count = 0
_tr = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)


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


def ring_area(ring):
    """경위도 링 → EPSG:5186 투영 후 신발끈 공식 면적(㎡)"""
    xs, ys = _tr.transform([p[0] for p in ring], [p[1] for p in ring])
    s = 0.0
    for i in range(len(xs) - 1):
        s += xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
    return abs(s) / 2.0


def geom_area(geom):
    t, c = geom["type"], geom["coordinates"]
    polys = c if t == "MultiPolygon" else [c]
    # 외곽 링 면적 - 내부 링(구멍) 면적
    return sum(ring_area(p[0]) - sum(ring_area(h) for h in p[1:]) for p in polys)


def fetch_dong_parcels(center, dong, dong_key):
    """동 중심 ±약 1km 박스의 필지 목록(동명 일치만).
    형식: [본번, 부번, 지목, 면적㎡] (본번·부번은 선행 0 제거 문자열)"""
    cache_f = PDONG_CACHE_DIR / f"{dong_key}.json"
    if cache_f.exists():
        return json.loads(cache_f.read_text(encoding="utf-8"))
    lng, lat = center
    box = f"BOX({lng-0.012},{lat-0.009},{lng+0.012},{lat+0.009})"
    out, seen = [], set()
    for page in range(1, 25):
        d = vw_get({"data": "LP_PA_CBND_BUBUN", "geomFilter": box, "size": "1000", "page": str(page)})
        if not d:
            break
        feats = d["result"]["featureCollection"]["features"]
        for f in feats:
            p = f["properties"]
            pnu = p.get("pnu") or ""
            if pnu in seen:
                continue
            seen.add(pnu)
            addr = p.get("addr") or ""
            if dong not in addr:
                continue
            bon = (p.get("bonbun") or "").lstrip("0")
            bu = (p.get("bubun") or "").lstrip("0")
            if not bon:
                continue
            # jibun 예: '39-573대' → 끝의 비숫자 = 지목
            jm = re.search(r"[^\d\-]+$", (p.get("jibun") or "").strip())
            jimok = jm.group(0) if jm else ""
            try:
                area = round(geom_area(f["geometry"]), 1)
            except Exception:
                continue
            if area > 0:
                out.append([bon, bu, jimok, area])
        if len(feats) < 1000:
            break
        time.sleep(0.05)
    PDONG_CACHE_DIR.mkdir(exist_ok=True)
    cache_f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def main():
    from geo_cache import GeoCache
    cache = json.loads(MATCH_CACHE.read_text(encoding="utf-8")) if MATCH_CACHE.exists() else {}
    geo = GeoCache(ADDR_CACHE, keyring.get_password("kakao", "api_key"))

    # 1) 전체 엑셀에서 마스킹 단독 매매 행 수집 (match_buildings와 동일 키 체계)
    keys = {}
    files = sorted(set(glob.glob(str(DATA / "*" / "실거래_*.xlsx"))))
    for f in files:
        try:
            df = pd.read_excel(f, sheet_name="단독다가구_매매", engine="openpyxl",
                               usecols=["시/도", "구/시", "법정동", "지번", "건축년도", "전용면적", "대지면적"])
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
            try:
                land = round(float(r["대지면적"]), 2)
            except (ValueError, TypeError):
                land = 0.0
            if by < 1900 or area <= 0 or not dong:
                continue
            mkey = f"{sido}|{gungu}|{dong}|{masked}|{by}|{area:.2f}"
            keys[mkey] = (sido, gungu, dong, masked, land)

    # 대상: 건물대장 방식이 못 잡았고(None/미처리) 대지면적이 있는 키만
    todo = {k: v for k, v in keys.items() if not cache.get(k) and v[4] > 0}
    dongs = sorted(set((v[0], v[1], v[2]) for v in todo.values()))
    print(f"[i] 전체 {len(keys)}키 / 필지매칭 대상 {len(todo)}키 / 대상 동 {len(dongs)}개")

    matched_n = 0
    try:
        for di, (sido, gungu, dong) in enumerate(dongs, 1):
            center = geo.get_coords(f"{sido} {gungu} {dong}")
            if not center:
                continue
            dong_key = f"{sido}_{gungu}_{dong}".replace(" ", "_").replace("/", "_")
            parcels = fetch_dong_parcels(center, dong, dong_key)

            for mk, (s, g, d, masked, land) in [(k, v) for k, v in todo.items()
                                                if (v[0], v[1], v[2]) == (sido, gungu, dong)]:
                patt = [(bon, bu, jimok, pa) for bon, bu, jimok, pa in parcels
                        if masked_match(masked, bon, bu)]
                if not patt:
                    continue
                tol_max = max(1.5, land * 0.02)  # 지적도형 면적 vs 대장 면적 오차 여유
                picked = None
                # 1) 계단식 허용오차: 가장 좁은 오차에서 유일하면 채택 (0.15 = 사실상 정확 일치)
                for tol in (0.15, 0.5, 1.5, tol_max):
                    hits = [(b, u, jm) for b, u, jm, pa in patt if abs(pa - land) <= tol]
                    uniq = sorted(set(f"{b}-{u}" if u else b for b, u, _ in hits))
                    if len(uniq) > 1:
                        # 복수면 지목 '대'(주택용지)만으로 재판정
                        uniq = sorted(set(f"{b}-{u}" if u else b for b, u, jm in hits if jm == "대"))
                        if len(uniq) != 1:
                            break
                    if len(uniq) == 1:
                        picked = uniq[0]
                        break
                # 2) margin 규칙: 최적 후보가 오차 내이고 2등과 1㎡ 이상 벌어지면 채택
                if not picked:
                    best = {}
                    for b, u, jm, pa in patt:
                        jib = f"{b}-{u}" if u else b
                        dd = abs(pa - land)
                        if jib not in best or dd < best[jib]:
                            best[jib] = dd
                    ranked = sorted(best.items(), key=lambda x: x[1])
                    if ranked[0][1] <= tol_max and (len(ranked) == 1 or ranked[1][1] - ranked[0][1] >= 1.0):
                        picked = ranked[0][0]
                if picked:
                    cache[mk] = picked
                    matched_n += 1

            if di % 20 == 0 or di == len(dongs):
                MATCH_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"  진행 {di}/{len(dongs)}동 | 신규매칭 {matched_n} | 요청 {req_count}")
    except RuntimeError as e:
        print(f"[!] {e} - 진행분 저장 후 종료 (재실행 시 이어서 진행)")
    finally:
        MATCH_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    total = sum(1 for v in cache.values() if v)
    print(f"[완료] 필지매칭 신규 {matched_n}건 | 누적 매칭 {total}/{len(cache)} ({total*100//max(1,len(cache))}%) | API 요청 {req_count}건")


if __name__ == "__main__":
    main()

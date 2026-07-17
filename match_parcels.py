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
BLDG_CACHE_DIR = DATA / "bldg_cache"
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
    """동 중심 ±약 1.6km 박스의 필지 목록(동명 일치만).
    v2 형식: [본번, 부번, 지목, 면적㎡, 중심경도, 중심위도] — 구형(4필드) 캐시는 재수집
    (박스 확장: 동 외곽 필지 누락으로 '패턴 필지 0'이던 751건 해소 목적)"""
    cache_f = PDONG_CACHE_DIR / f"{dong_key}.json"
    if cache_f.exists():
        cached = json.loads(cache_f.read_text(encoding="utf-8"))
        if cached and len(cached[0]) == 6:
            return cached
        # 구형 캐시(중심좌표 없음/빈 목록) → 확장 박스로 재수집
    # VWorld geomFilter BOX는 요청면적 10km² 제한 → 9.5km²(±1.6km×±1.5km)로 최대 확장
    lng, lat = center
    box = f"BOX({lng-0.018},{lat-0.0135},{lng+0.018},{lat+0.0135})"
    out, seen = [], set()
    for page in range(1, 41):
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
                g = f["geometry"]["coordinates"]
                ring = g[0][0] if f["geometry"]["type"] == "MultiPolygon" else g[0]
                cx = sum(pt[0] for pt in ring) / len(ring)
                cy = sum(pt[1] for pt in ring) / len(ring)
            except Exception:
                continue
            if area > 0:
                out.append([bon, bu, jimok, area, round(cx, 6), round(cy, 6)])
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
            keys[mkey] = (sido, gungu, dong, masked, land, by)

    # 대상: 건물대장 방식이 못 잡았고(None/미처리) 대지면적이 있는 키만
    todo = {k: v for k, v in keys.items() if not cache.get(k) and v[4] > 0}
    dongs = sorted(set((v[0], v[1], v[2]) for v in todo.values()))
    print(f"[i] 전체 {len(keys)}키 / 필지매칭 대상 {len(todo)}키 / 대상 동 {len(dongs)}개")

    matched_n = 0
    rule_n = [0, 0, 0]  # 계단식 / margin / 건물교차
    try:
        for di, (sido, gungu, dong) in enumerate(dongs, 1):
            center = geo.get_coords(f"{sido} {gungu} {dong}")
            if not center:
                continue
            dong_key = f"{sido}_{gungu}_{dong}".replace(" ", "_").replace("/", "_")
            parcels = fetch_dong_parcels(center, dong, dong_key)
            if not parcels:
                continue

            # 건물(대장) → 최근접 필지 배정: 50m 격자 해시로 근사 (교차 판별용, API 불필요)
            # bldg_cache v2 형식: [연도, 연면적, 대지면적, 경도, 위도]
            bldg_f = BLDG_CACHE_DIR / f"{dong_key}.json"
            blds = []
            if bldg_f.exists():
                blds = [b for b in json.loads(bldg_f.read_text(encoding="utf-8")) if len(b) == 5]
            grid = {}
            CELL = 0.0005  # ≈ 44~55m
            for i, p in enumerate(parcels):
                gk = (int(p[4] / CELL), int(p[5] / CELL))
                grid.setdefault(gk, []).append(i)
            bldg_parcel = []  # [(연도, 필지 인덱스)] — 45m 내 최근접 필지만
            for b in blds:
                bx, by_ = b[3], b[4]
                gk = (int(bx / CELL), int(by_ / CELL))
                best_i, best_d = -1, 1e9
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for i in grid.get((gk[0] + dx, gk[1] + dy), []):
                            p = parcels[i]
                            dd = ((p[4] - bx) * 88300) ** 2 + ((p[5] - by_) * 111320) ** 2
                            if dd < best_d:
                                best_d, best_i = dd, i
                if best_i >= 0 and best_d <= 45 ** 2:
                    bldg_parcel.append((b[0], best_i))

            for mk, (s, g, d, masked, land, by) in [(k, v) for k, v in todo.items()
                                                    if (v[0], v[1], v[2]) == (sido, gungu, dong)]:
                patt_i = [i for i, p in enumerate(parcels) if masked_match(masked, p[0], p[1])]
                if not patt_i:
                    continue
                jib_of = lambda p: f"{p[0]}-{p[1]}" if p[1] else p[0]
                tol_max = max(1.5, land * 0.02)  # 지적도형 면적 vs 대장 면적 오차 여유
                picked = None
                rule = -1
                # 1) 계단식 허용오차: 가장 좁은 오차에서 유일하면 채택 (0.15 = 사실상 정확 일치)
                for tol in (0.15, 0.5, 1.5, tol_max):
                    hits = [parcels[i] for i in patt_i if abs(parcels[i][3] - land) <= tol]
                    uniq = sorted(set(jib_of(p) for p in hits))
                    if len(uniq) > 1:
                        # 복수면 지목 '대'(주택용지)만으로 재판정
                        uniq = sorted(set(jib_of(p) for p in hits if p[2] == "대"))
                        if len(uniq) != 1:
                            break
                    if len(uniq) == 1:
                        picked, rule = uniq[0], 0
                        break
                # 2) margin 규칙: 최적 후보가 오차 내이고 2등과 1㎡ 이상 벌어지면 채택
                if not picked:
                    best = {}
                    for i in patt_i:
                        p = parcels[i]
                        jib = jib_of(p)
                        dd = abs(p[3] - land)
                        if jib not in best or dd < best[jib]:
                            best[jib] = dd
                    ranked = sorted(best.items(), key=lambda x: x[1])
                    if ranked[0][1] <= tol_max and (len(ranked) == 1 or ranked[1][1] - ranked[0][1] >= 1.0):
                        picked, rule = ranked[0][0], 1
                # 3) 건물 교차: 면적 후보가 복수여도 건축년도(±1) 건물이 얹힌 필지가 유일하면 채택
                if not picked and bldg_parcel:
                    cand_i = [i for i in patt_i if abs(parcels[i][3] - land) <= tol_max]
                    cand_jibs = {}
                    for i in cand_i:
                        cand_jibs.setdefault(jib_of(parcels[i]), set()).add(i)
                    if len(cand_jibs) >= 2:
                        yr_hit = {jib for jib, idxs in cand_jibs.items()
                                  if any(abs(y - by) <= 1 and pi in idxs for y, pi in bldg_parcel)}
                        if len(yr_hit) == 1:
                            picked, rule = yr_hit.pop(), 2
                if picked:
                    cache[mk] = picked
                    matched_n += 1
                    rule_n[rule] += 1

            if di % 20 == 0 or di == len(dongs):
                MATCH_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"  진행 {di}/{len(dongs)}동 | 신규매칭 {matched_n} (계단식 {rule_n[0]}/margin {rule_n[1]}/건물교차 {rule_n[2]}) | 요청 {req_count}")
    except RuntimeError as e:
        print(f"[!] {e} - 진행분 저장 후 종료 (재실행 시 이어서 진행)")
    finally:
        MATCH_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    total = sum(1 for v in cache.values() if v)
    print(f"[완료] 필지매칭 신규 {matched_n}건 | 누적 매칭 {total}/{len(cache)} ({total*100//max(1,len(cache))}%) | API 요청 {req_count}건")


if __name__ == "__main__":
    main()

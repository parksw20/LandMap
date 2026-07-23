# supply_area.py — 아파트 공급면적(전용+주거공용) 테이블 생성 → data/supply_area.json
#
# 원리: 건축HUB 주택인허가 '전유공용면적'(getHpExposPubuseAreaInfo)은 주택형(mgmTypeOulnPk)별로
#       전유/공용 면적을 행 단위로 준다.
#         공급면적 = 전유(exposPubuseGbCd=1) + 주건축물 공용(mainAtchGbCd=0)
#       지하주차장 등 부속건축물 공용은 계약면적 항목이므로 제외한다.
#
# 매칭: 응답의 platPlc(지번주소)를 우리 아파트 단지 주소와 대조 (이름 매칭보다 정확)
#
# 안전장치:
#  - 법정동 코드 목록/조회 결과 캐시(data/hspms_cache/) → 재실행 시 이어서 진행
#  - 쿼터 초과/미승인 시 진행분 저장 후 정상 종료
#
# 실행: python supply_area.py

import json
import sys
import time
import glob
from pathlib import Path
from collections import defaultdict

import keyring
import pandas as pd

from apt_info import api, items_of, extract_dong, Unauthorized, QuotaExceeded
import apt_info

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CACHE_DIR = DATA / "hspms_cache"
BJD_CACHE = CACHE_DIR / "bjd_map.json"
AREA_CACHE = CACHE_DIR / "area.json"
OUT = DATA / "supply_area.json"
LAWD = ROOT / "LAWD_서울_경기.csv"


def fetch_bjd_codes():
    """시군구별 단지목록에서 법정동 코드(bjdCode) 수집 — 아파트가 존재하는 동만"""
    if BJD_CACHE.exists():
        return json.loads(BJD_CACHE.read_text(encoding="utf-8"))
    lawd = pd.read_csv(LAWD, dtype=str)
    codes = set()
    for i, sgg in enumerate([c.strip() for c in lawd["LAWD_CD"] if str(c).strip()], 1):
        page = 1
        while page <= 30:
            resp = api("AptListService3/getSigunguAptList3",
                       {"sigunguCode": sgg, "pageNo": str(page)})
            its = items_of(resp)
            if not its:
                break
            for x in its:
                b = (x.get("bjdCode") or "").strip()
                if len(b) >= 10:
                    codes.add(b[:10])
            total = int(((resp.get("response") or {}).get("body") or {}).get("totalCount") or 0)
            if page * 100 >= total:
                break
            page += 1
        if i % 10 == 0:
            print(f"  법정동코드 {i}개 시군구 | 누적 {len(codes)}")
    out = sorted(codes)
    CACHE_DIR.mkdir(exist_ok=True)
    BJD_CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


def fetch_dong_areas(bjd):
    """법정동 단위 전유공용면적 전체 → [(platPlc, 전용, 공급)] (아파트 주택형만)"""
    sigungu, bjdong = bjd[:5], bjd[5:10]
    rows, page = [], 1
    while page <= 60:
        resp = api("HsPmsHubService/getHpExposPubuseAreaInfo",
                   {"sigunguCd": sigungu, "bjdongCd": bjdong,
                    "numOfRows": "100", "pageNo": str(page)})
        its = items_of(resp)
        if not its:
            break
        rows += its
        total = int(((resp.get("response") or {}).get("body") or {}).get("totalCount") or 0)
        if page * 100 >= total:
            break
        page += 1
        time.sleep(0.03)

    g = defaultdict(lambda: {"ex": 0.0, "pub": 0.0, "plc": "", "apt": False})
    for x in rows:
        key = x.get("mgmTypeOulnPk")
        if key is None:
            continue
        try:
            a = float(x.get("area") or 0)
        except (TypeError, ValueError):
            continue
        e = g[key]
        e["plc"] = x.get("platPlc") or e["plc"]
        if x.get("exposPubuseGbCdNm") == "전유":
            e["ex"] += a
            if (x.get("purpsCdNm") or "") == "아파트":
                e["apt"] = True
        elif x.get("mainAtchGbCdNm") == "주건축물":
            # 주거공용만 공급면적에 포함 (부속건축물=지하주차장 등은 계약면적)
            e["pub"] += a
    out = []
    for v in g.values():
        if v["apt"] and v["ex"] > 0 and v["pub"] > 0:
            out.append([v["plc"], round(v["ex"], 2), round(v["ex"] + v["pub"], 2)])
    return out


def norm_addr(a):
    """주소 정규화: 시도 접두어 제거 → '성동구 상왕십리동 12-37' 형태로 통일"""
    t = str(a).split()
    if t and (t[0].endswith("시") or t[0].endswith("도")) and len(t[0]) > 2:
        t = t[1:]
    return " ".join(t)


def load_our_apts():
    """실거래 아파트 단지: (단지명, 주소) → {법정동, 전용면적 집합}
    인허가 주소(대지 지번)와 실거래 주소(대표 지번)가 다른 경우가 많아
    주소가 아니라 '전용면적 세트'로 매칭한다. (예: 텐즈힐2단지 = 인허가 12-37 / 실거래 811)"""
    out = {}
    for f in glob.glob(str(DATA / "hierarchy" / "*" / "apt" / "details" / "*.json")):
        for x in json.loads(Path(f).read_text(encoding="utf-8")):
            name, addr = x.get("name", ""), x.get("address", "")
            if not name or not addr:
                continue
            k = (name, addr)
            e = out.setdefault(k, {"dong": extract_dong(addr), "areas": set()})
            for d in (x.get("deals") or []):
                try:
                    a = float(d.get("area") or 0)
                except (TypeError, ValueError):
                    continue
                if a > 0:
                    e["areas"].add(round(a, 2))
    return out


AREA_TOL = 0.15  # 전용면적 대조 허용 오차(㎡)


def match_by_areas(our_areas, cand_groups):
    """전용면적 세트 겹침으로 인허가 단지 선택.
    최고 점수가 1 이상이고 2등보다 확실히 클 때만 채택 (유일 매칭 원칙)."""
    scored = []
    for plc, types in cand_groups.items():
        hit = sum(1 for ex, _ in types
                  if any(abs(ex - a) <= AREA_TOL for a in our_areas))
        if hit:
            scored.append((hit, plc))
    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def main():
    CACHE_DIR.mkdir(exist_ok=True)
    areac = json.loads(AREA_CACHE.read_text(encoding="utf-8")) if AREA_CACHE.exists() else {}
    ours = load_our_apts()
    print(f"[i] 실거래 아파트 단지 주소 {len(ours)}개")

    stop = None
    try:
        bjds = fetch_bjd_codes()
        print(f"[i] 대상 법정동 {len(bjds)}개")
        todo = [b for b in bjds if b not in areac]
        for i, b in enumerate(todo, 1):
            areac[b] = fetch_dong_areas(b)
            if i % 25 == 0 or i == len(todo):
                AREA_CACHE.write_text(json.dumps(areac, ensure_ascii=False), encoding="utf-8")
                got = sum(len(v) for v in areac.values())
                print(f"  진행 {i}/{len(todo)}동 | 주택형 {got} | 요청 {apt_info.req_count}")
            time.sleep(0.03)
    except (Unauthorized, QuotaExceeded) as e:
        stop = str(e)
    except KeyboardInterrupt:
        stop = "중단"
    finally:
        AREA_CACHE.write_text(json.dumps(areac, ensure_ascii=False), encoding="utf-8")

    # 인허가 단지: 법정동 → {주소: [(전용, 공급)]}
    by_dong = defaultdict(lambda: defaultdict(list))
    for rows in areac.values():
        for plc, ex, sup in rows:
            by_dong[extract_dong(plc)][plc].append((ex, sup))

    out = {}
    for (name, addr), info in ours.items():
        cands = by_dong.get(info["dong"])
        if not cands or not info["areas"]:
            continue
        plc = match_by_areas(info["areas"], cands)
        if not plc:
            continue
        # 같은 전용면적 중복 제거 (동일 주택형이 여러 동에 반복)
        seen, uniq = set(), []
        for ex, sup in sorted(cands[plc]):
            k = round(ex, 1)
            if k in seen:
                continue
            seen.add(k)
            uniq.append([ex, sup])
        if uniq:
            out[f"{name}|{addr}"] = uniq
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    if stop:
        print(f"[!] {stop} — 진행분 저장 후 종료 (재실행 시 이어서 진행)")
    print(f"[완료] 공급면적 확보 단지 {len(out)}/{len(ours)} → {OUT.name} | API 요청 {apt_info.req_count}건")


if __name__ == "__main__":
    main()

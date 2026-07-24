# bldg_ledger.py — 건축물대장 기반 보완: 구축 공급면적 + 용적률·건폐율
#
# 배경: 주택인허가(supply_area.py)는 최근 건축분 위주라 1980년대 아파트는 7%만 커버된다.
#       건축물대장은 기존 건물 전체가 대상이라 구축까지 채울 수 있다.
#       표제부(getBrTitleInfo)에는 용적률·건폐율도 있어 VWorld 미확보분(48%)도 보완한다.
#
# 출력:
#   data/supply_area.json  — 기존 값 유지, 없는 단지만 추가 (인허가 값이 더 정확하므로 우선)
#   data/bldg_ratio.json   — 기존 값 유지, 없는 단지만 추가
#
# 안전장치:
#   - 법정동별 캐시(data/ledger_cache/) → 재실행 시 이어서 진행
#   - 미승인/쿼터 초과 시 진행분 저장 후 정상 종료
#
# 실행: python bldg_ledger.py

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from apt_info import api, items_of, Unauthorized, QuotaExceeded
import apt_info
from supply_area import (region_key, load_our_complexes, match_by_areas,
                         TYPE_PURPS, SUPPLY_PURPS)
from bldg_ratio import sane, num as rnum

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CACHE_DIR = DATA / "ledger_cache"
AREA_CACHE = CACHE_DIR / "area.json"
TITLE_CACHE = CACHE_DIR / "title.json"
BJD_MAP = DATA / "hspms_cache" / "bjd_map.json"
SUPPLY_OUT = DATA / "supply_area.json"
RATIO_OUT = DATA / "bldg_ratio.json"

# 전유공용면적의 세부 용도 (호별 용도는 '아파트'처럼 구체적으로 온다)
APT_PURPS = {"아파트", "연립주택", "다세대주택", "오피스텔", "도시형생활주택"}

# 표제부의 주용도는 상위 분류('공동주택')로 오므로 별도 집합이 필요하다.
# (여기서 APT_PURPS를 쓰면 아파트가 한 건도 안 걸린다 — 실측 확인)
TITLE_PURPS = {"공동주택", "오피스텔", "업무시설"}


def fetch_area(bjd):
    """법정동 전유공용면적 → [(platPlc, 전용, 공급, 용도)]"""
    sigungu, bjdong = bjd[:5], bjd[5:10]
    rows, page = [], 1
    while page <= 80:
        resp = api("BldRgstHubService/getBrExposPubuseAreaInfo",
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

    # 주택형(호) 단위로 전유/공용 합산 — 인허가와 동일한 산식
    g = defaultdict(lambda: {"ex": 0.0, "pub": 0.0, "plc": "", "purps": ""})
    for x in rows:
        key = (x.get("mgmBldrgstPk"), x.get("hoNm"))
        if not key[0]:
            continue
        try:
            a = float(x.get("area") or 0)
        except (TypeError, ValueError):
            continue
        e = g[key]
        e["plc"] = x.get("platPlc") or e["plc"]
        if x.get("exposPubuseGbCdNm") == "전유":
            e["ex"] += a
            p = (x.get("etcPurps") or x.get("mainPurpsCdNm") or "").strip()
            for cand in APT_PURPS:
                if cand in p:
                    e["purps"] = cand
                    break
        elif x.get("mainAtchGbCdNm") == "주건축물":
            e["pub"] += a

    out = []
    for v in g.values():
        if not (v["purps"] and v["ex"] > 0 and v["pub"] > 0):
            continue
        sup = v["ex"] + v["pub"]
        if not (0.40 <= v["ex"] / sup <= 0.95):   # 전용률 상식 범위
            continue
        out.append([v["plc"], round(v["ex"], 2), round(sup, 2), v["purps"]])
    return out


def fetch_title(bjd):
    """법정동 표제부 → {주소: (용적률, 건폐율, 사용승인연도)} — 공동주택만"""
    sigungu, bjdong = bjd[:5], bjd[5:10]
    out, page = {}, 1
    while page <= 80:
        resp = api("BldRgstHubService/getBrTitleInfo",
                   {"sigunguCd": sigungu, "bjdongCd": bjdong,
                    "numOfRows": "100", "pageNo": str(page)})
        its = items_of(resp)
        if not its:
            break
        for x in its:
            if (x.get("mainPurpsCdNm") or "") not in TITLE_PURPS:
                continue
            plc = (x.get("platPlc") or "").strip()
            vl, bc = sane(rnum(x.get("vlRat")), rnum(x.get("bcRat")))
            ap = (x.get("useAprDay") or "")[:4]
            by = int(ap) if ap.isdigit() else 0
            if not plc or (not vl and not bc):
                continue
            # 같은 주소에 여러 동이면 연면적이 가장 큰 것을 대표로
            area = rnum(x.get("totArea"))
            cur = out.get(plc)
            if not cur or area > cur[3]:
                out[plc] = (vl, bc, by, area)
        total = int(((resp.get("response") or {}).get("body") or {}).get("totalCount") or 0)
        if page * 100 >= total:
            break
        page += 1
        time.sleep(0.03)
    return {k: v[:3] for k, v in out.items()}


def main():
    CACHE_DIR.mkdir(exist_ok=True)
    areac = json.loads(AREA_CACHE.read_text(encoding="utf-8")) if AREA_CACHE.exists() else {}
    titlec = json.loads(TITLE_CACHE.read_text(encoding="utf-8")) if TITLE_CACHE.exists() else {}
    bjds = json.loads(BJD_MAP.read_text(encoding="utf-8"))
    print(f"[i] 대상 법정동 {len(bjds)}개 (수집됨 면적 {len(areac)} / 표제부 {len(titlec)})")

    stop = None
    try:
        todo = [b for b in bjds if b not in areac or b not in titlec]
        for i, b in enumerate(todo, 1):
            if b not in areac:
                areac[b] = fetch_area(b)
            if b not in titlec:
                titlec[b] = fetch_title(b)
            if i % 25 == 0 or i == len(todo):
                AREA_CACHE.write_text(json.dumps(areac, ensure_ascii=False), encoding="utf-8")
                TITLE_CACHE.write_text(json.dumps(titlec, ensure_ascii=False), encoding="utf-8")
                got = sum(len(v) for v in areac.values())
                print(f"  진행 {i}/{len(todo)}동 | 주택형 {got:,} | 요청 {apt_info.req_count:,}")
    except (Unauthorized, QuotaExceeded) as e:
        stop = str(e)
    except KeyboardInterrupt:
        stop = "중단"
    finally:
        AREA_CACHE.write_text(json.dumps(areac, ensure_ascii=False), encoding="utf-8")
        TITLE_CACHE.write_text(json.dumps(titlec, ensure_ascii=False), encoding="utf-8")

    # ── 공급면적 보완 (기존 인허가 값 우선, 없는 단지만 추가) ──
    supply = json.loads(SUPPLY_OUT.read_text(encoding="utf-8")) if SUPPLY_OUT.exists() else {}
    before_s = len(supply)
    by_purps = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for rows in areac.values():
        for plc, ex, sup, purps in rows:
            by_purps[purps][region_key(plc)][plc].append((ex, sup))

    for htype, purps_set in TYPE_PURPS.items():
        ours = load_our_complexes(htype)
        merged = defaultdict(lambda: defaultdict(list))
        for pu in purps_set:
            for region, plcs in by_purps.get(pu, {}).items():
                for plc, types in plcs.items():
                    merged[region][plc].extend(types)
        added = 0
        for (name, addr), info in ours.items():
            key = f"{name}|{addr}"
            if key in supply or not info["areas"]:
                continue
            cands = merged.get(info["region"])
            if not cands:
                continue
            plc = match_by_areas(info["areas"], cands)
            if not plc:
                continue
            seen, uniq = set(), []
            for ex, sup in sorted(cands[plc]):
                r = round(ex, 1)
                if r in seen:
                    continue
                seen.add(r)
                uniq.append([ex, sup])
            if uniq:
                supply[key] = uniq
                added += 1
        print(f"  [{htype}] 공급면적 보완 +{added}")
    SUPPLY_OUT.write_text(json.dumps(supply, ensure_ascii=False), encoding="utf-8")

    # ── 용적률·건폐율 보완 (주소 일치, 기존 값 우선) ──
    ratio = json.loads(RATIO_OUT.read_text(encoding="utf-8")) if RATIO_OUT.exists() else {}
    before_r = sum(1 for v in ratio.values() if v.get("vl") or v.get("bc"))
    title_by_region = {}
    for tmap in titlec.values():
        for plc, (vl, bc, by) in tmap.items():
            title_by_region.setdefault(region_key(plc), {})[plc] = (vl, bc, by)

    added_r = 0
    for key, v in ratio.items():
        if v.get("vl") or v.get("bc"):
            continue
        name, _, addr = key.partition("|")
        cands = title_by_region.get(region_key(addr))
        if not cands:
            continue
        # 같은 지번 주소를 우선, 없으면 건축년도가 일치하는 건물
        hit = None
        for plc, (vl, bc, by) in cands.items():
            if region_key(plc) == region_key(addr) and by and by == v.get("by"):
                hit = (vl, bc)
                break
        if hit:
            if hit[0]:
                v["vl"] = hit[0]
            if hit[1]:
                v["bc"] = hit[1]
            added_r += 1
    RATIO_OUT.write_text(json.dumps(ratio, ensure_ascii=False, separators=(",", ":")),
                         encoding="utf-8")

    after_r = sum(1 for v in ratio.values() if v.get("vl") or v.get("bc"))
    if stop:
        print(f"[!] {stop} — 진행분 저장 후 종료 (재실행 시 이어서 진행)")
    print(f"[완료] 공급면적 {before_s:,} → {len(supply):,} | "
          f"용적률·건폐율 {before_r:,} → {after_r:,} | API 요청 {apt_info.req_count:,}건")


if __name__ == "__main__":
    main()

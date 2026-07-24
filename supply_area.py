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

from apt_info import api, items_of, extract_dong, _DONG_RE, Unauthorized, QuotaExceeded
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


# 공급면적(전용+주거공용)으로 표기하는 용도들.
# 단독/다가구·토지·상가·공장은 공급면적 개념을 쓰지 않으므로 제외한다.
SUPPLY_PURPS = {"아파트", "연립주택", "다세대주택", "오피스텔", "도시형생활주택"}

# 우리 부동산 유형 → 인허가 용도 (분양권은 아파트 분양이므로 아파트로 대조)
TYPE_PURPS = {
    "apt": {"아파트"},
    "rh": {"연립주택", "다세대주택", "도시형생활주택"},
    "off": {"오피스텔"},
    "silv": {"아파트"},
}


def fetch_dong_areas(bjd):
    """법정동 단위 전유공용면적 → [(platPlc, 전용, 공급, 용도)]
    v2: 용도를 함께 저장해 아파트 외 유형(연립·다세대·오피스텔)도 지원"""
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

    g = defaultdict(lambda: {"ex": 0.0, "pub": 0.0, "plc": "", "purps": ""})
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
            p = (x.get("purpsCdNm") or "").strip()
            if p in SUPPLY_PURPS:
                e["purps"] = p
        elif x.get("mainAtchGbCdNm") == "주건축물":
            # 주거공용만 공급면적에 포함 (부속건축물=지하주차장 등은 계약면적)
            e["pub"] += a
    out = []
    for v in g.values():
        if not (v["purps"] and v["ex"] > 0 and v["pub"] > 0):
            continue
        sup = v["ex"] + v["pub"]
        # 전용률이 상식 범위를 벗어나면 집계 오류(부대시설이 주거공용에 섞인 경우 등) → 제외.
        # 주거용 전용률은 통상 60~85%다.
        if not (0.40 <= v["ex"] / sup <= 0.95):
            continue
        out.append([v["plc"], round(v["ex"], 2), round(sup, 2), v["purps"]])
    return out


_SIDO_SUFFIX = ("특별시", "광역시", "특별자치시", "특별자치도")


def norm_addr(a):
    """주소 정규화: 시도 접두어만 제거 → '성남시 분당구 삼평동 705' 형태로 통일.

    주의: 첫 토큰이 '시'로 끝난다고 무조건 자르면 안 된다.
    우리 실거래 주소는 경기도가 생략돼 '성남시 …'로 시작하므로,
    그렇게 자르면 시(市)가 사라져 인허가 주소('경기도 성남시 …')와 키가 어긋난다.
    """
    t = str(a).split()
    if t and (t[0].endswith(_SIDO_SUFFIX) or t[0].endswith("도")):
        t = t[1:]
    return " ".join(t)


def region_key(addr):
    """지번을 뺀 '시군구 + 법정동' 키.
    동 이름만으로 묶으면 성남 정자동과 수원 정자동이 섞여 엉뚱한 단지가 매칭된다
    (실제로 파크뷰(분당 정자동)에 수원 정자동 단지의 주택형이 붙는 사고 발생)."""
    t = norm_addr(addr).split()
    for i in range(len(t) - 1, -1, -1):
        if _DONG_RE.match(t[i]) and not t[i].endswith(("시", "군", "구", "도")):
            return " ".join(t[:i + 1])
    return ""


def load_our_complexes(htype):
    """실거래 단지: (단지명, 주소) → {지역키, 전용면적 집합}
    인허가 주소(대지 지번)와 실거래 주소(대표 지번)가 다른 경우가 많아
    주소가 아니라 '전용면적 세트'로 매칭한다. (예: 텐즈힐2단지 = 인허가 12-37 / 실거래 811)"""
    out = {}
    for f in glob.glob(str(DATA / "hierarchy" / "*" / htype / "details" / "*.json")):
        for x in json.loads(Path(f).read_text(encoding="utf-8")):
            name, addr = x.get("name", ""), x.get("address", "")
            if not name or not addr:
                continue
            k = (name, addr)
            e = out.setdefault(k, {"region": region_key(addr), "areas": set()})
            for d in (x.get("deals") or []):
                try:
                    a = float(d.get("area") or 0)
                except (TypeError, ValueError):
                    continue
                if a > 0:
                    e["areas"].add(round(a, 2))
    return out


AREA_TOL = 0.15  # 전용면적 대조 허용 오차(㎡)


MIN_COVERAGE = 0.5   # 우리 거래 면적 중 인허가 주택형으로 설명되는 최소 비율


def match_by_areas(our_areas, cand_groups):
    """전용면적 세트 겹침으로 인허가 단지 선택.

    점수는 '우리 거래 면적 중 몇 종류가 설명되는가'로 센다.
    인허가 주택형 수로 세면 84.92·84.97 두 타입이 우리 84.99 하나에 걸려 2점이 되어,
    84㎡처럼 흔한 면적 하나만 겹쳐도 엉뚱한 단지가 뽑힌다(파크뷰 오매칭 원인).

    채택 조건: 2등보다 점수가 높고(유일성), 우리 면적의 절반 이상을 설명할 것.
    """
    total = len(our_areas)
    if not total:
        return None
    scored = []
    for plc, types in cand_groups.items():
        hit, err = 0, 0.0
        for a in our_areas:
            d = min((abs(ex - a) for ex, _ in types), default=99)
            if d <= AREA_TOL:
                hit += 1
                err += d
        if hit:
            scored.append((hit, err, plc))
    if not scored:
        return None
    # 많이 설명하는 순 → 같으면 면적이 더 정확히 맞는 순
    scored.sort(key=lambda x: (-x[0], x[1]))
    best_hit, best_err, plc = scored[0]
    if best_hit / total < MIN_COVERAGE:
        return None      # 흔한 면적 하나만 겹친 경우 — 채택 안 함(전용면적으로 대체)
    # 동점이면서 오차까지 사실상 같으면 진짜 모호 → 보류
    if len(scored) > 1 and scored[1][0] == best_hit and abs(scored[1][1] - best_err) < 0.01:
        return None
    return plc


def main():
    CACHE_DIR.mkdir(exist_ok=True)
    areac = json.loads(AREA_CACHE.read_text(encoding="utf-8")) if AREA_CACHE.exists() else {}
    # v1 캐시(용도 없음)는 재수집 대상 — 아파트만 담겨 있어 다른 유형을 지원할 수 없다
    if areac:
        sample = next((v for v in areac.values() if v), None)
        if sample and len(sample[0]) < 4:
            print("[i] 구형 캐시(용도 없음) 감지 → 전 동 재수집")
            areac = {}

    stop = None
    try:
        bjds = fetch_bjd_codes()
        print(f"[i] 대상 법정동 {len(bjds)}개")
        # 기본은 증분(미수집 동만). 이미 수집한 동에 새 아파트가 지어지면 반영되지 않으므로
        # 주기적으로 --refresh 로 전 동을 다시 받아 신축을 반영한다.
        if "--refresh" in sys.argv:
            print("[i] --refresh: 전 동 재수집")
            todo = list(bjds)
        else:
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

    # 용도별 인허가 색인: 용도 → 지역키 → {주소: [(전용, 공급)]}
    by_purps = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for rows in areac.values():
        for rec in rows:
            if len(rec) < 4:
                continue
            plc, ex, sup, purps = rec
            # 캐시에 남아 있는 비정상 전용률도 여기서 한 번 더 거른다 (재수집 불필요)
            if not (sup > 0 and 0.40 <= ex / sup <= 0.95):
                continue
            by_purps[purps][region_key(plc)][plc].append((ex, sup))

    out, stats = {}, {}
    for htype, purps_set in TYPE_PURPS.items():
        ours = load_our_complexes(htype)
        if not ours:
            continue
        # 이 유형이 참조할 인허가 후보를 지역키 단위로 합친다
        merged = defaultdict(lambda: defaultdict(list))
        for pu in purps_set:
            for region, plcs in by_purps.get(pu, {}).items():
                for plc, types in plcs.items():
                    merged[region][plc].extend(types)
        hit = 0
        for (name, addr), info in ours.items():
            cands = merged.get(info["region"])
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
                out.setdefault(f"{name}|{addr}", uniq)
                hit += 1
        stats[htype] = (hit, len(ours))
        print(f"  [{htype}] 공급면적 확보 {hit}/{len(ours)}")

    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    if stop:
        print(f"[!] {stop} — 진행분 저장 후 종료 (재실행 시 이어서 진행)")
    print(f"[완료] 전체 {len(out)}개 단지 → {OUT.name} | API 요청 {apt_info.req_count}건")


if __name__ == "__main__":
    main()

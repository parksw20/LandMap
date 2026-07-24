# no_deal_apts.py — 실거래 이력이 없는 K-apt 등록 아파트 → data/no_deal_apts.json
#
# 배경: 지도에는 '거래가 있었던' 단지만 나온다. 거래가 한 번도 없던 단지는 아예 보이지 않아
#       그 자리에 아파트가 있는지조차 알 수 없다. K-apt 등록 단지 중 우리 실거래 데이터와
#       매칭되지 않은 것들을 주소·좌표와 함께 모아 회색 마커로 표시한다.
#
# 한계: K-apt는 의무관리대상(대체로 300세대 이상)만 등록되어 서울+경기 8,339개뿐이다.
#       따라서 '모든 아파트'가 아니라 '등록 아파트 중 거래 없는 것'을 보완하는 성격이다.
#
# 안전장치:
#  - 주소/좌표 캐시(data/kapt_cache/addr.json) → 재실행 시 이어서 진행
#  - 쿼터 초과/미승인 시 진행분 저장 후 정상 종료
#
# 실행: python no_deal_apts.py

import glob
import json
import re
import sys
import time
from pathlib import Path

import keyring

from apt_info import (api, items_of, build_kapt_index, lookup_kapt,
                      load_our_complexes, _int, Unauthorized, QuotaExceeded)
import apt_info
from geo_cache import GeoCache

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CACHE_DIR = DATA / "kapt_cache"
LIST_CACHE = CACHE_DIR / "list.json"
DETAIL_CACHE = CACHE_DIR / "detail.json"
ADDR_CACHE = CACHE_DIR / "addr.json"
GEO_CACHE = DATA / "address_cache.json"
OUT = DATA / "no_deal_apts.json"


SIDO_RE = re.compile(
    r"^(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|"
    r"세종특별자치시|경기도|강원특별자치도|강원도|충청북도|충청남도|전라북도|"
    r"전북특별자치도|전라남도|경상북도|경상남도|제주특별자치도)\s*")


def addr_key(addr, name=""):
    """지번 주소 비교용 키 (프론트엔드 addrKey와 동일 규칙).
    K-apt '서울특별시 성동구 용답동 253- 청계 sk view 아파트' ↔ 실거래 '성동구 용답동 253'
    """
    s = SIDO_RE.sub("", str(addr or ""))
    s = re.sub(r"\s+", "", s)
    nm = re.sub(r"\s+", "", str(name or ""))
    if nm and s.endswith(nm):
        s = s[:-len(nm)]
    s = re.sub(r"번지$", "", s)
    s = re.sub(r"-+$", "", s)
    # K-apt는 '성남분당구'처럼 시(市)를 생략하는데 실거래는 '성남시분당구'로 쓴다
    return re.sub(r"시(?=[가-힣]+구)", "", s, count=1)


def real_addr_keys():
    """실거래 아파트 단지의 주소 키 집합 — 이 주소면 '거래 있는 단지'다"""
    keys = set()
    for f in glob.glob(str(DATA / "hierarchy" / "*" / "apt" / "details" / "*.json")):
        try:
            rows = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        for x in rows:
            k = addr_key(x.get("address"), x.get("name"))
            if k:
                keys.add(k)
    return keys


def fetch_addr(kapt_code):
    """단지 기본정보에서 법정동 주소·세대수·사용승인일 — 좌표 확보용"""
    b = items_of(api("AptBasisInfoServiceV4/getAphusBassInfoV4", {"kaptCode": kapt_code}))
    if not b:
        return None
    p = b[0]
    addr = (p.get("kaptAddr") or "").strip()
    if not addr:
        return None
    return {
        "addr": addr,
        "name": (p.get("kaptName") or "").strip(),
        "hh": _int(p.get("kaptdaCnt")),
        "dg": _int(p.get("kaptDongCnt")),
        "approval": (p.get("kaptUsedate") or "").strip(),
    }


def main():
    if not LIST_CACHE.exists():
        print("(!) K-apt 목록 캐시 없음 — 먼저 apt_info.py 실행")
        sys.exit(1)
    CACHE_DIR.mkdir(exist_ok=True)
    listc = json.loads(LIST_CACHE.read_text(encoding="utf-8"))
    detailc = json.loads(DETAIL_CACHE.read_text(encoding="utf-8")) if DETAIL_CACHE.exists() else {}
    addrc = json.loads(ADDR_CACHE.read_text(encoding="utf-8")) if ADDR_CACHE.exists() else {}

    # 실거래 데이터와 매칭된 단지코드 = '거래가 있는 단지'
    ours = load_our_complexes()
    kidx = build_kapt_index(listc)
    idx_by_dong = {}
    for (d, kn), c in kidx.items():
        idx_by_dong.setdefault(d, []).append((kn, c))
    matched = set()
    for (dong, nname), _ in ours.items():
        c = lookup_kapt(idx_by_dong, kidx, dong, nname)
        if c:
            matched.add(c)

    targets = [c for lst in listc.values() for c in lst if c["code"] not in matched]
    print(f"[i] K-apt 전체 {sum(len(v) for v in listc.values())} / 거래 있는 단지 {len(matched)}")
    print(f"[i] 거래 이력 없는 단지 {len(targets)}개 — 주소 수집 대상 {len([t for t in targets if t['code'] not in addrc])}개")

    stop = None
    try:
        todo = [t for t in targets if t["code"] not in addrc]
        for i, t in enumerate(todo, 1):
            info = fetch_addr(t["code"])
            addrc[t["code"]] = info or {}
            if i % 50 == 0 or i == len(todo):
                ADDR_CACHE.write_text(json.dumps(addrc, ensure_ascii=False), encoding="utf-8")
                print(f"  주소 {i}/{len(todo)} | 요청 {apt_info.req_count}")
            time.sleep(0.03)
    except (Unauthorized, QuotaExceeded) as e:
        stop = str(e)
    except KeyboardInterrupt:
        stop = "중단"
    finally:
        ADDR_CACHE.write_text(json.dumps(addrc, ensure_ascii=False), encoding="utf-8")

    # 주소 → 좌표 (기존 지오코딩 캐시 재사용)
    geo = GeoCache(GEO_CACHE, keyring.get_password("kakao", "api_key"))
    # 단지명 매칭만으로는 표기 차이('청계 sk view 아파트'↔'청계SKVIEW')를 못 잡아
    # 거래가 있는 단지가 대거 '거래없음'으로 분류됐다. 주소로 한 번 더 걸러낸다.
    real_keys = real_addr_keys()
    out, miss, dup = [], 0, 0
    for t in targets:
        info = addrc.get(t["code"]) or {}
        addr = info.get("addr")
        if not addr:
            miss += 1
            continue
        if addr_key(addr, info.get("name") or t["name"]) in real_keys:
            dup += 1
            continue
        coords = geo.get_coords(addr)
        if not coords:
            miss += 1
            continue
        d = detailc.get(t["code"]) or {}
        rec = {
            "name": info.get("name") or t["name"],
            "address": addr,
            "coords": [round(coords[0], 7), round(coords[1], 7)],
        }
        hh = info.get("hh") or d.get("households")
        if hh:
            rec["hh"] = hh
        if info.get("dg"):
            rec["dg"] = info["dg"]
        ap = (info.get("approval") or "")[:4]
        if ap.isdigit():
            rec["by"] = int(ap)
        out.append(rec)

    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    geo.save()
    if stop:
        print(f"[!] {stop} — 진행분 저장 후 종료 (재실행 시 이어서 진행)")
    print(f"[완료] 진짜 거래없음 {len(out)}개 / 실거래 존재로 제외 {dup}개 / "
          f"주소·좌표 실패 {miss}개 → {OUT.name} | API 요청 {apt_info.req_count}건")


if __name__ == "__main__":
    main()

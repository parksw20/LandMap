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

import json
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
    out, miss = [], 0
    for t in targets:
        info = addrc.get(t["code"]) or {}
        addr = info.get("addr")
        if not addr:
            miss += 1
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
    print(f"[완료] 좌표 확보 {len(out)}개 / 좌표 실패 {miss}개 → {OUT.name} | API 요청 {apt_info.req_count}건")


if __name__ == "__main__":
    main()

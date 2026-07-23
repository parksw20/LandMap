# apt_info.py — 공동주택 단지정보(세대수·주차대수 등) 수집 → data/apt_info.json
#
# 원리: 시군구 단위로 단지목록(kaptCode)을 받고, 단지별 기본/상세 정보를 조회해
#       우리 실거래 데이터의 아파트 단지(단지명 + 법정동)와 매칭한다.
#
# 호출 절감:
#  - 목록은 시군구 단위(67개)로 조회 — 법정동 단위(12,279개) 대비 대폭 절감
#  - 상세 조회는 '거래 건수 많은 단지' 우선 — 하루 쿼터에 걸려 중단돼도 자주 보는 단지부터 채워짐
#
# 안전장치:
#  - 목록/상세 캐시(data/kapt_cache/) → 재실행 시 API 재호출 없음 (중단 후 이어서 진행)
#  - 쿼터 초과/미승인 감지 시 진행분 저장 후 정상 종료
#
# 실행: python apt_info.py

import json
import re
import sys
import time
import glob
from pathlib import Path
from urllib.parse import unquote

import keyring
import requests
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CACHE_DIR = DATA / "kapt_cache"
LIST_CACHE = CACHE_DIR / "list.json"
DETAIL_CACHE = CACHE_DIR / "detail.json"
OUT = DATA / "apt_info.json"
LAWD = ROOT / "LAWD_서울_경기.csv"

BASE = "https://apis.data.go.kr/1613000"
KEY = unquote((keyring.get_password("data_go_kr", "parksw20") or "").strip())
if not KEY:
    print("(!) data.go.kr 키 없음"); sys.exit(1)

req_count = 0


class Unauthorized(Exception):
    pass


class QuotaExceeded(Exception):
    pass


def api(path, params, retries=3):
    """data.go.kr 호출. 403(미승인)/쿼터 초과는 예외로 올려 상위에서 안전 종료."""
    global req_count
    for i in range(retries):
        try:
            r = requests.get(f"{BASE}/{path}",
                             params={"serviceKey": KEY, "_type": "json",
                                     "numOfRows": "100", "pageNo": "1", **params},
                             timeout=20)
            req_count += 1
            if r.status_code == 403:
                raise Unauthorized("403 Forbidden — 활용신청 미승인 또는 반영 대기")
            txt = r.text
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in txt or "요청횟수" in txt:
                raise QuotaExceeded("일일 트래픽 초과")
            if r.status_code != 200:
                time.sleep(1 + i)
                continue
            try:
                return r.json()
            except ValueError:
                # XML 오류 응답(미승인/파라미터 오류 등)
                if "SERVICE_KEY_IS_NOT_REGISTERED" in txt:
                    raise Unauthorized("서비스 키 미등록")
                return None
        except (Unauthorized, QuotaExceeded):
            raise
        except Exception:
            time.sleep(1 + i)
    return None


def items_of(resp):
    """data.go.kr 표준 응답에서 item 리스트 추출 (단건이면 dict로 오는 것 방어)"""
    if not resp:
        return []
    body = (resp.get("response") or {}).get("body") or {}
    it = body.get("items")
    if not it:
        return []
    if isinstance(it, dict):
        it = it.get("item") or []
    if isinstance(it, dict):
        it = [it]
    return it if isinstance(it, list) else []


def fetch_sigungu_list(sigungu_code):
    """시군구 단지목록 (페이징) → [{code, name, dong}]"""
    out, page = [], 1
    while page <= 30:
        resp = api("AptListService3/getSigunguAptList3",
                   {"sigunguCode": sigungu_code, "pageNo": str(page)})
        its = items_of(resp)
        if not its:
            break
        for x in its:
            code = (x.get("kaptCode") or "").strip()
            name = (x.get("kaptName") or "").strip()
            dong = (x.get("bjdName") or x.get("as3") or "").strip()
            if code and name:
                out.append({"code": code, "name": name, "dong": dong})
        total = ((resp.get("response") or {}).get("body") or {}).get("totalCount") or 0
        if page * 100 >= int(total or 0):
            break
        page += 1
        time.sleep(0.05)
    return out


def fetch_detail(kapt_code):
    """단지 기본+상세 → 세대수·주차대수·사용승인일 등"""
    d = {}
    b = items_of(api("AptBasisInfoServiceV3/getAphusBassInfoV3", {"kaptCode": kapt_code}))
    if b:
        p = b[0]
        d["households"] = _int(p.get("kaptdaCnt"))       # 세대수
        d["dongs"] = _int(p.get("kaptDongCnt"))          # 동수
        d["approval"] = (p.get("kaptUsedate") or "").strip()  # 사용승인일
        d["builder"] = (p.get("kaptBcompany") or "").strip()  # 시공사
    time.sleep(0.03)
    s = items_of(api("AptBasisInfoServiceV3/getAphusDtlInfoV3", {"kaptCode": kapt_code}))
    if s:
        p = s[0]
        # 지하 + 지상 주차대수
        d["parking"] = _int(p.get("kaptdPcntu")) + _int(p.get("kaptdPcnt"))
    return d


def _int(v):
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (ValueError, TypeError):
        return 0


def norm_name(s):
    """단지명 정규화: 공백/괄호/'아파트' 접미사 제거 후 비교용 키"""
    s = re.sub(r"\(.*?\)", "", str(s))
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"아파트$", "", s)
    return s


def load_our_complexes():
    """실거래 데이터의 아파트 단지: {(동, 정규화단지명)} → (단지명, 주소, 거래건수)"""
    comps = {}
    for f in glob.glob(str(DATA / "hierarchy" / "*" / "apt" / "details" / "*.json")):
        for x in json.loads(Path(f).read_text(encoding="utf-8")):
            name, addr = x.get("name", ""), x.get("address", "")
            parts = addr.split()
            dong = parts[2] if len(parts) >= 3 else ""
            if not name or not dong:
                continue
            k = (dong, norm_name(name))
            cur = comps.get(k)
            n = len(x.get("deals") or [])
            if cur:
                comps[k] = (cur[0], cur[1], cur[2] + n)
            else:
                comps[k] = (name, addr, n)
    return comps


def main():
    CACHE_DIR.mkdir(exist_ok=True)
    listc = json.loads(LIST_CACHE.read_text(encoding="utf-8")) if LIST_CACHE.exists() else {}
    detailc = json.loads(DETAIL_CACHE.read_text(encoding="utf-8")) if DETAIL_CACHE.exists() else {}

    ours = load_our_complexes()
    print(f"[i] 실거래 아파트 단지 {len(ours)}개")

    lawd = pd.read_csv(LAWD, dtype=str)
    codes = [c.strip() for c in lawd["LAWD_CD"].tolist() if c and str(c).strip()]

    stop = None
    try:
        # 1) 시군구 단지목록
        for i, sgg in enumerate(codes, 1):
            if sgg in listc:
                continue
            listc[sgg] = fetch_sigungu_list(sgg)
            if i % 5 == 0 or i == len(codes):
                LIST_CACHE.write_text(json.dumps(listc, ensure_ascii=False), encoding="utf-8")
                print(f"  목록 {i}/{len(codes)} 시군구 | 누적단지 {sum(len(v) for v in listc.values())} | 요청 {req_count}")
        LIST_CACHE.write_text(json.dumps(listc, ensure_ascii=False), encoding="utf-8")

        # 2) K-apt 단지 → (동, 정규화명) 색인
        kapt_idx = {}
        for lst in listc.values():
            for c in lst:
                kapt_idx.setdefault((c["dong"], norm_name(c["name"])), c["code"])

        # 3) 매칭되는 단지만, 거래 많은 순으로 상세 조회
        targets = []
        for k, (name, addr, n) in ours.items():
            code = kapt_idx.get(k)
            if code:
                targets.append((n, code, name, addr))
        targets.sort(reverse=True)
        print(f"[i] 단지목록 매칭 {len(targets)}/{len(ours)} — 거래 많은 순으로 상세 조회")

        for j, (n, code, name, addr) in enumerate(targets, 1):
            if code in detailc:
                continue
            detailc[code] = fetch_detail(code)
            if j % 50 == 0:
                DETAIL_CACHE.write_text(json.dumps(detailc, ensure_ascii=False), encoding="utf-8")
                print(f"  상세 {j}/{len(targets)} | 요청 {req_count}")
            time.sleep(0.03)
    except (Unauthorized, QuotaExceeded) as e:
        stop = str(e)
    finally:
        LIST_CACHE.write_text(json.dumps(listc, ensure_ascii=False), encoding="utf-8")
        DETAIL_CACHE.write_text(json.dumps(detailc, ensure_ascii=False), encoding="utf-8")

    # 4) 프론트엔드 룩업 테이블 저장: "단지명|주소" → 정보
    kapt_idx = {}
    for lst in listc.values():
        for c in lst:
            kapt_idx.setdefault((c["dong"], norm_name(c["name"])), c["code"])
    out = {}
    for k, (name, addr, n) in ours.items():
        code = kapt_idx.get(k)
        d = detailc.get(code) if code else None
        if not d:
            continue
        rec = {}
        if d.get("households"):
            rec["hh"] = d["households"]
        if d.get("parking"):
            rec["pk"] = d["parking"]
        if d.get("dongs"):
            rec["dg"] = d["dongs"]
        if rec:
            out[f"{name}|{addr}"] = rec
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    if stop:
        print(f"[!] {stop} — 진행분 저장 후 종료 (재실행 시 이어서 진행)")
    print(f"[완료] 정보 확보 단지 {len(out)}개 → {OUT.name} | API 요청 {req_count}건")


if __name__ == "__main__":
    main()

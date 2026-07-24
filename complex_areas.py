# complex_areas.py — 단지별 '전 기간' 주택형 목록 → data/areas_<유형>.json
#
# 배경: 평형 칩은 선택한 기간의 거래에서만 뽑히므로, '현재 월'만 보면 그 달에 거래된
#       평형 하나만 보인다. 단지에 어떤 평형이 있는지는 기간과 무관한 정보이므로
#       전체 월(19개월)의 거래를 모아 단지별 주택형 목록을 미리 만들어 둔다.
#
# 인허가(supply_area.json)에 없는 단지도 이걸로 평형 구성을 볼 수 있다.
#
# 실행: python complex_areas.py

import json
import glob
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
TYPES = ["apt", "rh", "off", "silv", "sh", "nrg", "land", "indu"]


def build(htype):
    """구(시군구) → {단지명|주소: 전용면적 목록} — 전 기간 합집합.
    상세 파일과 같은 구 단위로 샤딩해, 화면에 보이는 구만 받도록 한다
    (연립/다세대는 단일 파일이면 8MB라 모바일에서 부담)."""
    acc = defaultdict(lambda: defaultdict(set))
    for f in glob.glob(str(DATA / "hierarchy" / "*" / htype / "details" / "*.json")):
        gungu = Path(f).stem          # 예: 서울특별시_강남구
        try:
            rows = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  (!) 읽기 실패 {Path(f).name}: {e}")
            continue
        for x in rows:
            name, addr = x.get("name", ""), x.get("address", "")
            if not name:
                continue
            key = f"{name}|{addr}"
            for d in (x.get("deals") or []):
                try:
                    a = float(d.get("area") or 0)
                except (TypeError, ValueError):
                    continue
                if a > 0:
                    acc[gungu][key].add(round(a, 2))
    # 같은 평(㎡ 반올림)으로 묶이는 값은 대표 하나만 남겨 파일 크기를 줄인다
    out = {}
    for gungu, table in acc.items():
        red = {}
        for k, areas in table.items():
            seen, keep = set(), []
            for a in sorted(areas):
                r = round(a)
                if r in seen:
                    continue
                seen.add(r)
                keep.append(a)
            red[k] = keep
        out[gungu] = red
    return out


def main():
    for t in TYPES:
        shards = build(t)
        if not shards:
            continue
        d = DATA / "areas" / t
        d.mkdir(parents=True, exist_ok=True)
        total = biggest = 0
        for gungu, table in shards.items():
            p = d / f"{gungu}.json"
            p.write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            total += len(table)
            biggest = max(biggest, p.stat().st_size)
        print(f"[{t}] 단지 {total:,}개 / 구 {len(shards)}개 | 최대 샤드 {biggest/1024:,.0f}KB")


if __name__ == "__main__":
    main()

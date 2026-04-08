import json
import os
from pathlib import Path

BASE_DIR = Path(r"C:\cli\PROJECT\부동산\data\hierarchy")
ym = "202604"
t = "apt"

def make_stats(base_price, count, area=84.5):
    return {
        "total": count, "sale": count//2, "sale_range": [base_price, base_price+10000],
        "jeonse": count//4, "jeonse_range": [base_price//2, base_price//2+5000],
        "monthly": count//4, "monthly_range": [1000, 2000],
        "price_range": [1000, base_price+10000], "rep_area": area, "rep_avg_price": base_price
    }

path = BASE_DIR / ym / t
det_path = path / "details"
det_path.mkdir(parents=True, exist_ok=True)

# 1. Summary
sido = [{"name": "서울특별시", "coords": [126.9780, 37.5665], "stats": make_stats(150000, 100)}]
gungu = [{"name": "서울특별시 강남구", "sido": "서울특별시", "coords": [127.0473, 37.5172], "stats": make_stats(200000, 50)}]
dong = [{"name": "개포동", "parent": "서울특별시 강남구", "coords": [127.0573, 37.4892], "stats": make_stats(220000, 20)}]

with open(path / "summary_sido.json", "w", encoding="utf-8") as f: json.dump(sido, f, indent=2, ensure_ascii=False)
with open(path / "summary_gungu.json", "w", encoding="utf-8") as f: json.dump(gungu, f, indent=2, ensure_ascii=False)
with open(path / "summary_dong.json", "w", encoding="utf-8") as f: json.dump(dong, f, indent=2, ensure_ascii=False)

# 2. Detail
details = [{
    "name": "개포자이프레지던스", "address": "서울특별시 강남구 개포동 189", "coords": [127.0673, 37.4792],
    "stats": make_stats(250000, 10),
    "deals": [{"type": "매매", "price": 250000, "rent": 0, "area": 84.5, "land": 35.0, "floor": "10", "dong": "101", "date": "2026-04-01", "period": "", "renew": "", "p_dep": 0, "p_rent": 0}]
}]
with open(det_path / "서울특별시_강남구.json", "w", encoding="utf-8") as f:
    json.dump(details, f, indent=2, ensure_ascii=False)

# 3. Manifest
with open(Path(r"C:\cli\PROJECT\부동산\data\manifest.json"), "w", encoding="utf-8") as f:
    json.dump([ym], f, indent=2, ensure_ascii=False)

print("검증용 샘플 데이터 생성 완료")

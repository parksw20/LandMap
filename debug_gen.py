import pandas as pd
import json
import os
from pathlib import Path

BASE_DIR = Path(r"C:\cli\PROJECT\부동산\data")
CACHE_PATH = BASE_DIR / "address_cache.json"

with open(CACHE_PATH, "r", encoding="utf-8") as f:
    cache = json.load(f)

file_path = BASE_DIR / "2026" / "실거래_202603_v2604050114.xlsx"
print(f"Reading {file_path}...")
xls = pd.ExcelFile(file_path)

# Only Apartment for speed
sheets = [s for s in xls.sheet_names if "아파트" in s]
full_data = []
for sn in sheets:
    print(f"Reading sheet: {sn}")
    df = pd.read_excel(xls, sheet_name=sn)
    tx_type = '매매' if '매매' in sn else '전세'
    df['__tx_type'] = tx_type
    
    # Simple addr find
    cols = df.columns.tolist()
    name_col = next((c for c in cols if '단지명' in str(c) or '건물명' in str(c)), None)
    sido_col = next((c for c in cols if '시도' in str(c)), None)
    gungu_col = next((c for c in cols if '군구' in str(c)), None)
    dong_col = next((c for c in cols if '법정동' in str(c)), None)
    jibeon_col = next((c for c in cols if '지번' in str(c)), None)

    def make_addr(row):
        parts = []
        for c in [sido_col, gungu_col, dong_col, jibeon_col]:
            if c and not pd.isna(row[c]): parts.append(str(row[c]))
        return " ".join(parts).strip()

    df['__address'] = df.apply(make_addr, axis=1)
    df['__name'] = df[name_col] if name_col else df['__address']
    full_data.append(df)

merged_df = pd.concat(full_data, ignore_index=True)
print(f"Merged {len(merged_df)} rows.")

def get_c(a):
    c = cache.get(str(a).strip())
    if c and len(c)==2:
        v1, v2 = float(c[0]), float(c[1])
        return [v2, v1] if v1 < v2 else [v1, v2]
    return None

merged_df['__coords'] = merged_df['__address'].apply(get_c)
valid_df = merged_df.dropna(subset=['__coords'])
print(f"Valid coordinates: {len(valid_df)} rows.")

features = []
for name, group in valid_df.groupby('__name'):
    lng, lat = group.iloc[0]['__coords']
    deals = []
    for _, row in group.iterrows():
        p = row.to_dict()
        clean_p = {str(k): v for k, v in p.items() if not str(k).startswith('__') and not pd.isna(v)}
        clean_p['거래유형'] = p['__tx_type']
        deals.append(clean_p)
    
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {
            "name": str(name),
            "deals": deals
        }
    })

out_path = BASE_DIR / "2026" / "geojson" / "실거래_202603_apt.geojson"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, indent=2)
print(f"Saved to {out_path} ({out_path.stat().st_size} bytes)")

import json
import pandas as pd
import os
import re
from pathlib import Path

class HierarchyBuilder:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir).resolve()

    def _get_type_stats(self, df, tx_type):
        sub_df = df[df['__tx_type'] == tx_type]
        if sub_df.empty: return None
        
        def get_range(d):
            return [int(d['__price'].min()), int(d['__price'].max())]

        valid_area_df = sub_df[sub_df['__area'] > 0].copy()
        rep_area = 0
        avg_price = 0
        if not valid_area_df.empty:
            valid_area_df['_rounded_area'] = valid_area_df['__area'].round(1)
            modes = valid_area_df['_rounded_area'].mode()
            if not modes.empty:
                rep_area = float(modes[0])
                avg_price = int(valid_area_df[valid_area_df['_rounded_area'] == rep_area]['__price'].mean())

        return {
            "count": len(sub_df),
            "range": get_range(sub_df),
            "rep_area": rep_area,
            "rep_avg_price": avg_price
        }

    def _get_stats(self, df):
        return {
            "total": len(df),
            "sale": self._get_type_stats(df, '매매'),
            "jeonse": self._get_type_stats(df, '전세'),
            "monthly": self._get_type_stats(df, '월세')
        }

    def _save_json(self, data, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def build_incremental(self, df):
        if df.empty: return
        ym = re.sub(r'[^0-9]', '', str(df.iloc[0]['__ym']))
        h_type = re.sub(r'[^a-zA-Z]', '', str(df.iloc[0]['__h_type']))
        
        target_dir = self.base_dir / "hierarchy" / ym / h_type
        os.makedirs(target_dir, exist_ok=True)

        # Summary (Level 1-3)
        sido_s = [{"name": n, "coords": g.iloc[0]['__coords'], "stats": self._get_stats(g)} for n, g in df.groupby('__sido') if n]
        self._save_json(sido_s, target_dir / "summary_sido.json")
        
        gungu_s = [{"name": f"{s} {gu}", "sido": s, "coords": g.iloc[0]['__coords'], "stats": self._get_stats(g)} for (s, gu), g in df.groupby(['__sido', '__gungu']) if gu]
        self._save_json(gungu_s, target_dir / "summary_gungu.json")
        
        dong_s = [{"name": d, "parent": f"{s} {gu}", "coords": g.iloc[0]['__coords'], "stats": self._get_stats(g)} for (s, gu, d), g in df.groupby(['__sido', '__gungu', '__dong']) if d]
        self._save_json(dong_s, target_dir / "summary_dong.json")

        # Details
        det_path = target_dir / "details"
        for (sido, gungu), g in df.groupby(['__sido', '__gungu']):
            if not gungu: continue
            c_data = []
            for (addr, name), cg in g.groupby(['__address', '__name']):
                deals = []
                for _, r in cg.iterrows():
                    deals.append({
                        "type": r['__tx_type'], "price": int(r['__price']), "rent": int(r['__rent']), 
                        "area": float(r['__area']), "land": float(r['__land']),
                        "floor": str(r['__floor']), "dong": str(r['__bdong']), "date": str(r['__date']),
                        "period": str(r['__period']), "renew": str(r['__renew']),
                        "p_dep": int(r['__p_dep']), "p_rent": int(r['__p_rent'])
                    })
                c_data.append({"name": name, "address": addr, "coords": cg.iloc[0]['__coords'], "stats": self._get_stats(cg), "deals": deals})
            
            clean_gungu = str(gungu).replace("/", "_").replace(" ", "_")
            fname = f"{sido}_{clean_gungu}.json"
            self._save_details_custom(c_data, det_path / fname)

    def _save_details_custom(self, data, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("[\n")
            for i, item in enumerate(data):
                f.write("  {\n")
                f.write(f'    "name": "{item["name"]}",\n')
                f.write(f'    "address": "{item["address"]}",\n')
                f.write(f'    "coords": {json.dumps(item["coords"])},\n')
                f.write(f'    "stats": {json.dumps(item["stats"], ensure_ascii=False)},\n')
                f.write('    "deals": [\n')
                for j, deal in enumerate(item["deals"]):
                    comma = "," if j < len(item["deals"]) - 1 else ""
                    f.write(f'      {json.dumps(deal, ensure_ascii=False)}{comma}\n')
                f.write('    ]\n')
                f.write("  }" + ("," if i < len(data) - 1 else "") + "\n")
            f.write("]")

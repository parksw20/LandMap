import pandas as pd
import time
import os
from pathlib import Path
from geo_cache import GeoCache
from excel_parser import ExcelParser
from hierarchy_builder import HierarchyBuilder

# 현재 스크립트 위치 기준 상대 경로 사용 (한글 인코딩 문제 방지)
ROOT_DIR = Path(__file__).parent
BASE_DIR = ROOT_DIR / "data"
CACHE_PATH = BASE_DIR / "address_cache.json"
KAKAO_API_KEY = "159ba18d11b27a623f31a3d175030e55"
TYPE_MAP = {'apt': '아파트', 'rh': '빌라', 'sh': '주택', 'off': '오피스텔'}

class DataManager:
    def __init__(self):
        print(f"  > 주소 캐시 로딩 중...")
        self.geo = GeoCache(CACHE_PATH, KAKAO_API_KEY)
        self.parser = ExcelParser(TYPE_MAP)
        self.builder = HierarchyBuilder(BASE_DIR)
        self.global_index = {} # (건물명, 주소)를 키로 중복 제거

    def run(self):
        print("\n[부동산 데이터 통합 관리 시스템 시작]")
        
        for yr in ["2026", "2025"]:
            d = BASE_DIR / yr
            if not d.exists(): continue
            for f in sorted(d.glob("실거래_*.xlsx"), reverse=True):
                if "_geocoded" in f.name: continue
                print(f"\n  > 파일 처리 시작: {f.name}")
                
                df = self.parser.parse_file(f)
                if df.empty: continue
                
                unique_addrs = df['__address'].unique()
                print(f"    - 주소 확인 중 ({len(df)}건 / 유니크 {len(unique_addrs)}건)...")
                addr_map = {addr: self.geo.get_coords(addr) for addr in unique_addrs}
                
                df['__coords'] = df['__address'].map(addr_map)
                df = df.dropna(subset=['__coords'])
                
                if not df.empty:
                    # 검색 인덱스 수집 (건물명)
                    for (name, addr), g in df.groupby(['__name', '__address']):
                        key = (name, addr)
                        if key not in self.global_index:
                            self.global_index[key] = {
                                "n": name, "a": addr, "c": g.iloc[0]['__coords'], "t": "complex"
                            }
                    
                    # 검색 인덱스 수집 (법정동)
                    for dong, g in df.groupby('__dong'):
                        if dong not in self.global_index:
                            self.global_index[dong] = {
                                "n": dong, "c": g.iloc[0]['__coords'], "t": "dong"
                            }

                    for h_type, group in df.groupby('__h_type'):
                        if h_type != 'unknown':
                            self.builder.build_incremental(group)
                    
                    # 파일 하나 처리할 때마다 캐시 저장
                    self.geo.save()
                
                self.update_manifest()
        
        # 통합 검색 인덱스 저장
        self.save_global_index()
                
        print("\n[작업 완료] 모든 데이터 가공 및 통합 검색 인덱스 생성이 완료되었습니다.")

    def save_global_index(self):
        print(f"  > 통합 검색 인덱스 생성 중 ({len(self.global_index)}건)...")
        index_data = list(self.global_index.values())
        with open(BASE_DIR / "global_search_index.json", "w", encoding="utf-8") as f:
            import json
            json.dump(index_data, f, ensure_ascii=False, indent=0)

    def update_manifest(self):
        h_dir = BASE_DIR / "hierarchy"
        if not h_dir.exists(): return
        ym_list = sorted([d.name for d in h_dir.iterdir() if d.is_dir()], reverse=True)
        import json
        with open(BASE_DIR / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(ym_list, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    DataManager().run()

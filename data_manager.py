# `data_manager.py` 실행 시 특정 연월만 갱신할 수 있는 명령줄 인수(`-m YYYYMM`) 추가 및 `manifest.json` 기반의 기처리 데이터 스킵(Skip) 로직 적용.

import pandas as pd
import time
import os
import json
import argparse
import re
from pathlib import Path
from geo_cache import GeoCache
from excel_parser import ExcelParser
from hierarchy_builder import HierarchyBuilder

# 현재 스크립트 위치 기준 상대 경로 사용
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
        self.manifest = self._load_manifest()

    def _load_manifest(self):
        m_path = BASE_DIR / "manifest.json"
        if m_path.exists():
            with open(m_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def load_existing_indexes(self):
        """이미 처리된 월의 검색 인덱스를 로드하여 통합 인덱스에 합침"""
        print(f"  > 기존 검색 인덱스 병합 중...")
        h_dir = BASE_DIR / "hierarchy"
        if not h_dir.exists(): return

        for ym_dir in h_dir.iterdir():
            if not ym_dir.is_dir(): continue
            for type_dir in ym_dir.iterdir():
                if not type_dir.is_dir(): continue
                idx_file = type_dir / "search_index.json"
                if idx_file.exists():
                    with open(idx_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for item in data:
                            # n: 이름, a: 주소, c: 좌표
                            key = (item['n'], item.get('a', ''))
                            if key not in self.global_index:
                                self.global_index[key] = {
                                    "n": item['n'], "a": item.get('a', ''), "c": item['c'], "t": "complex"
                                }
            
            # 법정동 인덱스는 summary_dong.json에서 추출
            for type_dir in ym_dir.iterdir():
                dong_file = type_dir / "summary_dong.json"
                if dong_file.exists():
                    with open(dong_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for item in data:
                            if item['name'] not in self.global_index:
                                self.global_index[item['name']] = {
                                    "n": item['name'], "c": item['coords'], "t": "dong"
                                }

    def run(self, target_month=None):
        print("\n[부동산 데이터 통합 관리 시스템 시작]")
        
        # 기존 데이터 인덱스 먼저 로드
        self.load_existing_indexes()

        for yr in ["2026", "2025"]:
            d = BASE_DIR / yr
            if not d.exists(): continue
            
            # 파일명에서 연월 추출 (예: 실거래_202604_v... -> 202604)
            for f in sorted(d.glob("실거래_*.xlsx"), reverse=True):
                match = re.search(r'실거래_(\d{6})', f.name)
                if not match: continue
                file_ym = match.group(1)

                # 특정 월 지정 시 해당 월만 처리
                if target_month and file_ym != target_month:
                    continue
                
                # 특정 월 지정이 없고, 이미 manifest에 있으면 스킵
                if not target_month and file_ym in self.manifest:
                    print(f"  - 스킵 (이미 처리됨): {file_ym} ({f.name})")
                    continue

                print(f"\n  > 파일 처리 시작: {f.name}")
                df = self.parser.parse_file(f)
                if df.empty: continue
                
                unique_addrs = df['__address'].unique()
                print(f"    - 주소 확인 중 ({len(df)}건 / 유니크 {len(unique_addrs)}건)...")
                addr_map = {addr: self.geo.get_coords(addr) for addr in unique_addrs}
                
                df['__coords'] = df['__address'].map(addr_map)
                df = df.dropna(subset=['__coords'])
                
                if not df.empty:
                    # 신규 데이터 인덱스 수집
                    for (name, addr), g in df.groupby(['__name', '__address']):
                        key = (name, addr)
                        self.global_index[key] = {"n": name, "a": addr, "c": g.iloc[0]['__coords'], "t": "complex"}
                    
                    for dong, g in df.groupby('__dong'):
                        self.global_index[dong] = {"n": dong, "c": g.iloc[0]['__coords'], "t": "dong"}

                    for h_type, group in df.groupby('__h_type'):
                        if h_type != 'unknown':
                            self.builder.build_incremental(group)
                    
                    self.geo.save()
                
                self.update_manifest()
        
        self.save_global_index()
        print("\n[작업 완료] 모든 데이터 가공 및 통합 검색 인덱스 생성이 완료되었습니다.")

    def save_global_index(self):
        print(f"  > 통합 검색 인덱스 생성 중 ({len(self.global_index)}건)...")
        index_data = list(self.global_index.values())
        with open(BASE_DIR / "global_search_index.json", "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=0)

    def update_manifest(self):
        h_dir = BASE_DIR / "hierarchy"
        if not h_dir.exists(): return
        ym_list = sorted([d.name for d in h_dir.iterdir() if d.is_dir()], reverse=True)
        with open(BASE_DIR / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(ym_list, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="부동산 데이터 관리 도구")
    parser.add_argument("-m", "--month", type=str, help="처리할 특정 연월 (예: 202604)")
    args = parser.parse_args()

    DataManager().run(target_month=args.month)

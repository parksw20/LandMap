# `data_manager.py` 실행 시 특정 연월만 갱신할 수 있는 명령줄 인수(`-m YYYYMM`) 추가 및 `manifest.json` 기반의 기처리 데이터 스킵(Skip) 로직 적용.

import pandas as pd
import time
import os
import json
import argparse
import re
import keyring # 추가
from pathlib import Path
from geo_cache import GeoCache
from excel_parser import ExcelParser
from hierarchy_builder import HierarchyBuilder

# 현재 스크립트 위치 기준 상대 경로 사용
ROOT_DIR = Path(__file__).parent
BASE_DIR = ROOT_DIR / "data"
CACHE_PATH = BASE_DIR / "address_cache.json"

# Keyring에서 키 가져오기 (없을 경우 안내)
KAKAO_API_KEY = keyring.get_password("kakao", "api_key")
if not KAKAO_API_KEY:
    print("(!) 오류: 카카오 API 키가 설정되지 않았습니다.")
    print("    설정 방법: python -c \"import keyring; keyring.set_password('kakao', 'api_key', '내_키_값')\"")
    # 개발 편의를 위해 일단 실행은 되게 하되, 실제 API 호출 시 에러가 날 것입니다.

TYPE_MAP = {
    'apt': '아파트', 'rh': '빌라', 'sh': '주택', 'off': '오피스텔',
    'nrg': '상가', 'land': '토지', 'silv': '분양권', 'indu': '공장창고',
}

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

    def run(self, target_month=None, rebuild=False):
        print("\n[부동산 데이터 통합 관리 시스템 시작]")
        if rebuild:
            print("  > 전체 재생성 모드: manifest 스킵 없이 모든 월을 다시 처리합니다.")

        # 기존 데이터 인덱스 먼저 로드 (재생성 시에는 오염된 기존 좌표를 재사용하지 않음)
        if not rebuild:
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
                
                # 특정 월 지정이 없고, 이미 manifest에 있으면 스킵 (재생성 모드는 스킵 안 함)
                if not rebuild and not target_month and file_ym in self.manifest:
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

                # 시도/구/동 요약 마커용 '고정' 좌표: 거래 좌표가 아닌 지역명 자체를 지오코딩
                # (유형(apt/rh/sh)마다 동 마커 위치가 달라지는 문제 해결)
                if not df.empty:
                    self._attach_region_coords(df)

                if not df.empty:
                    # 신규 데이터 인덱스 수집
                    for (name, addr), g in df.groupby(['__name', '__address']):
                        key = (name, addr)
                        self.global_index[key] = {"n": name, "a": addr, "c": g.iloc[0]['__coords'], "t": "complex"}
                    
                    for dong, g in df.groupby('__dong'):
                        first = g.iloc[0]
                        self.global_index[dong] = {"n": dong, "c": first.get('__dong_coords', first['__coords']), "t": "dong"}

                    for h_type, group in df.groupby('__h_type'):
                        if h_type != 'unknown':
                            self.builder.build_incremental(group)
                    
                    self.geo.save()
                
                self.update_manifest()
        
        self.save_global_index()
        print("\n[작업 완료] 모든 데이터 가공 및 통합 검색 인덱스 생성이 완료되었습니다.")

    def _attach_region_coords(self, df):
        """시도/구/동 canonical 좌표 컬럼(__sido_coords/__gungu_coords/__dong_coords) 추가.
        지역명 지오코딩 실패 시 해당 행의 거래 좌표(__coords)로 폴백."""
        sido_map, gungu_map, dong_map = {}, {}, {}
        for _, r in df[['__sido', '__gungu', '__dong']].drop_duplicates().iterrows():
            s, g, d = r['__sido'], r['__gungu'], r['__dong']
            if s and s not in sido_map:
                sido_map[s] = self.geo.get_coords(s)
            if g and (s, g) not in gungu_map:
                gungu_map[(s, g)] = self.geo.get_coords(f"{s} {g}".strip())
            if d and (s, g, d) not in dong_map:
                dong_map[(s, g, d)] = self.geo.get_coords(f"{s} {g} {d}".strip())
        df['__sido_coords'] = df.apply(lambda r: sido_map.get(r['__sido']) or r['__coords'], axis=1)
        df['__gungu_coords'] = df.apply(lambda r: gungu_map.get((r['__sido'], r['__gungu'])) or r['__coords'], axis=1)
        df['__dong_coords'] = df.apply(lambda r: dong_map.get((r['__sido'], r['__gungu'], r['__dong'])) or r['__coords'], axis=1)

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
    parser.add_argument("-r", "--rebuild", action="store_true", help="manifest 무시하고 전체 월 재생성 (좌표 로직 변경 후 필수)")
    args = parser.parse_args()

    DataManager().run(target_month=args.month, rebuild=args.rebuild)

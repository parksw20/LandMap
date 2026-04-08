import json
import os
import requests
import time
from pathlib import Path

class GeoCache:
    def __init__(self, cache_path, api_key):
        self.cache_path = Path(cache_path)
        self.api_key = api_key
        self.raw_cache = {}
        self.full_cache = {}
        self.sub_cache = {}
        
        print(f"      ... 캐시 로딩 시작: {self.cache_path.name}")
        if self.cache_path.exists():
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self.raw_cache = json.load(f)
            self._rebuild_indices()
        
        print(f"      ... 유효 캐시 {len(self.full_cache)}건 로드 완료")

    def _rebuild_indices(self):
        self.full_cache = {}
        self.sub_cache = {}
        for k, v in self.raw_cache.items():
            if v and len(v) == 2 and v[0] is not None:
                clean_k = str(k).replace(" ", "")
                coords = [float(v[0]), float(v[1])]
                self.full_cache[clean_k] = coords
                
                parts = str(k).split()
                if len(parts) >= 2:
                    sub_k = "".join(parts[-2:]).replace(" ", "")
                    if sub_k not in self.sub_cache:
                        self.sub_cache[sub_k] = coords

    def save(self):
        print(f"      ... 캐시 저장 중 ({len(self.raw_cache)}건)")
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.raw_cache, f, ensure_ascii=False, indent=2)

    def get_coords(self, address):
        if not address: return None
        
        # 1. 캐시 확인
        clean_addr = str(address).replace(" ", "")
        if clean_addr in self.full_cache:
            return self.full_cache[clean_addr]
        
        parts = str(address).split()
        if len(parts) >= 2:
            sub_addr = "".join(parts[-2:]).replace(" ", "")
            if sub_addr in self.sub_cache:
                return self.sub_cache[sub_addr]
        
        # 2. API 호출
        return self._fetch_api(address)

    def _fetch_api(self, address):
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {self.api_key}"}
        try:
            r = requests.get(url, headers=headers, params={"query": address}, timeout=5)
            r.raise_for_status()
            data = r.json()
            docs = data.get("documents", [])
            if docs:
                coords = [float(docs[0]["x"]), float(docs[0]["y"])]
                self.raw_cache[address] = coords
                # 인덱스 즉시 업데이트
                self.full_cache[address.replace(" ", "")] = coords
                parts = address.split()
                if len(parts) >= 2:
                    sub_k = "".join(parts[-2:]).replace(" ", "")
                    if sub_k not in self.sub_cache:
                        self.sub_cache[sub_k] = coords
                return coords
            else:
                self.raw_cache[address] = [None, None]
                return None
        except Exception as e:
            print(f"      (!) API 오류 ({address}): {e}")
            return None

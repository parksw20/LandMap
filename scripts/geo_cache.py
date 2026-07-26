import json
import os
import re
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

    def get_coords(self, address, place=None, region=None):
        """place: 지번 지오코딩이 실패했을 때 키워드로 위치를 찾을 단지명(아파트 등).
        region: 키워드 검색 결과가 엉뚱한 지역으로 튀지 않게 검증할 '시군구'."""
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
        coords = self._fetch_api(address)
        if coords:
            return coords

        # 2.5. 단지명 키워드 폴백 — 지번이 카카오 DB에 없는 신축 등에서,
        #      '자양동 863'(존재하지 않는 지번)이 동 중심으로 잘못 찍히는 것을 막는다.
        #      키워드 결과 주소가 요청한 시군구와 같을 때만 채택(엉뚱한 지역 방지).
        if place:
            coords = self._fetch_keyword(place, region or (parts[0] if parts else ""))
            if coords:
                self._store(str(address).strip(), coords)
                return coords

        # 3. 폴백 사다리 — 카카오 DB에 없는 지번(특수지번 등)이나 일시 실패로
        #    매물이 통째로 드랍되는 것을 방지. 정확도는 낮아져도 위치는 유지한다.
        addr = str(address).strip()
        # 3-1. 부번 제거: '명일동 228-8' → '명일동 228'
        m = re.match(r'^(.+\d+)-\d+$', addr)
        if m:
            coords = self._fetch_api(m.group(1))
            if coords:
                self._store(addr, coords)
                return coords
        # 3-2. 지번 제거(동 단위): '종로구 인사동 280' → '종로구 인사동'
        parts = addr.split()
        if len(parts) >= 2 and re.search(r'\d', parts[-1]):
            dong_addr = " ".join(parts[:-1])
            coords = self._fetch_api(dong_addr)
            if coords:
                self._store(addr, coords)
                return coords
        return None

    def _store(self, address, coords):
        """폴백으로 얻은 좌표를 원래 주소 키로 캐시 (다음 실행부터 즉시 히트)"""
        self.raw_cache[address] = coords
        self.full_cache[address.replace(" ", "")] = coords

    def _fetch_keyword(self, place, region):
        """장소명(단지명) 키워드 검색 → 좌표. region(시군구)이 결과 주소에 포함될 때만 채택."""
        url = "https://dapi.kakao.com/v2/local/search/keyword.json"
        headers = {"Authorization": f"KakaoAK {self.api_key}"}
        gu = str(region or "").split()[-1] if region else ""
        query = f"{gu} {place}".strip()
        try:
            r = requests.get(url, headers=headers, params={"query": query, "size": 5}, timeout=5)
            r.raise_for_status()
            for d in r.json().get("documents", []):
                addr = d.get("address_name", "") or d.get("road_address_name", "")
                if gu and gu not in addr:
                    continue     # 다른 지역 결과 배제
                return [float(d["x"]), float(d["y"])]
        except Exception as e:
            print(f"      (!) 키워드 오류 ({query}): {e}")
        return None

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

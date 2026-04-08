# 실행 python geocode_ex.py -d data/2026
# 엑셀 파일을 json화 시켜줌

import pandas as pd
import requests
import json
import time
import os
import re
import sys
import pickle
import threading
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

# -------------------------------------------------------------------------
# 설정
# -------------------------------------------------------------------------

KAKAO_API_ENV_VAR = "KAKAO_API_KEY"
CACHE_FILE_NAME = "address_cache.json"

# -------------------------------------------------------------------------
# 로깅 / 유틸
# -------------------------------------------------------------------------

def log(msg: str):
    print(f"[LOG] {msg}", flush=True)

# -------------------------------------------------------------------------
# 카카오맵 API 키 가져오기
# -------------------------------------------------------------------------

def get_kakao_key() -> str:
    """
    1. 환경 변수 KAKAO_API_KEY 확인
    2. 없으면 keyring 확인 (서비스명: 'kakao_api', 유저명: 'key') - 선택사항
    3. 없으면 사용자 입력
    """
    key = os.environ.get(KAKAO_API_ENV_VAR)
    if key:
        return key.strip()

    try:
        import keyring
        key = keyring.get_password("kakao_api", "parksw20")
        if key:
            return key.strip()
    except ImportError:
        pass

    log("카카오 API 키를 찾을 수 없습니다.")
    key = input("카카오 REST API 키를 입력하세요: ").strip()
    if not key:
        raise ValueError("API 키가 필요합니다.")
    return key

# -------------------------------------------------------------------------
# 지오코딩 (캐싱 + Thread Safe)
# -------------------------------------------------------------------------

def load_cache(cache_path: Path) -> dict[str, list[float] | None]:
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"캐시 로드 실패: {e}")
    return {}

def save_cache(cache_path: Path, cache: dict):
    try:
        if not cache_path.parent.exists():
            log(f"Parent dir missing, creating: {cache_path.parent}")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            
        # Atomic write with unique temp file to avoid collisions
        # and improve Windows handling
        temp_path = cache_path.with_name(f"{cache_path.stem}_{uuid.uuid4()}.tmp")
        
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
            
        try:
            temp_path.replace(cache_path)
        except OSError as e:
            # Windows [WinError 183] handling: explicit remove then rename
            if getattr(e, 'winerror', 0) == 183 or e.errno == 17:
                log(f"Replace failed ({e}), attempting remove+rename...")
                try:
                    time.sleep(0.1) # Wait briefly for lock release
                    if cache_path.exists():
                        os.remove(cache_path)
                    os.rename(temp_path, cache_path)
                except Exception as e2:
                    log(f"Retry failed: {e2}")
                    # Clean up temp if possible (silent fail ok)
                    try: os.remove(temp_path)
                    except: pass
            else:
                try: os.remove(temp_path)
                except: pass
                raise e
            
    except Exception as e:
        log(f"캐시 저장 실패: {e} | Path: {cache_path.resolve()}")
        # Clean up temp if it exists
        try:
            if 'temp_path' in locals() and temp_path.exists():
                os.remove(temp_path)
        except: pass

_cache_lock = threading.Lock()

def geocode_address(address: str, api_key: str, cache: dict[str, list[float] | None]) -> list[float] | None:
    """
    address -> [lng, lat] (float list) or None
    Cache lookup included.
    """
    if not isinstance(address, str) or not address.strip():
        return None
    
    clean_addr = address.strip()

    # 1. 락 사용하여 캐시 확인
    with _cache_lock:
        if clean_addr in cache:
            return cache[clean_addr]
    
    # 2. API 요청
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"query": clean_addr}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        documents = data.get("documents", [])
        
        result = None
        if documents:
            # 첫 번째 결과 사용
            x = float(documents[0]["x"]) # lng
            y = float(documents[0]["y"]) # lat
            result = [x, y]
        
        # 3. 락 사용하여 캐시 업데이트
        with _cache_lock:
            cache[clean_addr] = result
        
        return result

    except Exception as e:
        log(f"API Error ({clean_addr}): {e}")
        return None

# -------------------------------------------------------------------------
# 데이터 처리 메인 로직
# -------------------------------------------------------------------------

def process_excel_file(
    infile: Path,
    kakao_key: str,
    cooldown: float = 0.2, # Unused in thread pool but kept for signature
    include_sheets: list[str] | None = None,
    normalize_seoul: bool = True,
    cache: dict[str, list[float|None]] | None = None,
    cache_path: Path | None = None,
    autosave_every: int = 1000,
) -> tuple[Path, list[Path]] | None:
    """
    엑셀 파일을 읽어서 지오코딩 및 GeoJSON 생성 (Lite + Detail 구조)
    Return: (geocoded_excel_path, list_of_geojson_paths)
    """
    log(f"파일 처리 시작: {infile.name}")
    
    try:
        xls = pd.ExcelFile(infile)
    except Exception as e:
        log(f"엑셀 열기 실패: {infile} - {e}")
        return None

    if include_sheets:
        target_sheets = [s for s in xls.sheet_names if s in include_sheets]
    else:
        target_sheets = xls.sheet_names

    if not target_sheets:
        log("처리할 시트가 없습니다.")
        return None
    
    # 출력 경로 준비
    # data/2025/calc_202501.xlsx -> data/2025/geojson/...
    out_geo_dir = infile.parent / "geojson"
    out_geo_dir.mkdir(exist_ok=True)
    
    # 지오코딩 결과를 저장할 엑셀 파일 경로
    out_xls_name = infile.stem + "_geocoded.xlsx"
    out_xls = infile.parent / out_xls_name
    
    # 이미 지오코딩된 파일이 있으면 로드해서 재사용 (Regeneration 지원)
    existing_dfs = {}
    if out_xls.exists():
        log(f"기존 지오코딩 파일 로드: {out_xls.name}")
        try:
            with pd.ExcelFile(out_xls) as existing_xls:
                for sheet in existing_xls.sheet_names:
                    existing_dfs[sheet] = pd.read_excel(existing_xls, sheet_name=sheet)
        except Exception:
            log("기존 파일 로드 실패, 새로 생성합니다.")
    
    generated_files = []
    
    # 엑셀 writer 준비
    # 주의: 기존 파일이 있어도 덮어쓰거나, 아예 로직을 분리해야 함.
    # 여기서는 "기존 파일이 있으면 읽어서 df로 만들고, 부족한 부분만 채우거나 그대로 사용" 한 뒤 다시 씀.
    
    # 결과 데이터를 모을 dict (sheet_name -> df)
    result_dfs = {}

    for sheet_name in target_sheets:
        # 이미 처리된 데이터가 있는지 확인
        if sheet_name in existing_dfs:
            df = existing_dfs[sheet_name]
            # 위경도 컬럼 있는지 확인
            if 'lat' in df.columns and 'lng' in df.columns:
                # 이미 완료된 것으로 간주
                # 단, GeoJSON은 다시 생성해야 할 수 있으므로 result_dfs에 추가
                result_dfs[sheet_name] = df
                # continue # GeoJSON 생성을 위해 continue 하지 않고 진행
            else:
                # 컬럼 없으면 원본에서 다시 읽기
                df = pd.read_excel(xls, sheet_name=sheet_name)
        else:
             df = pd.read_excel(xls, sheet_name=sheet_name)

        # 필수 컬럼 확인
        has_addr_col = '주소' in df.columns
        has_legacy_cols = '시군구' in df.columns and '번지' in df.columns
        
        if not (has_addr_col or has_legacy_cols):
             log(f"  [Skip] {sheet_name}: 필수 컬럼(주소 or 시군구+번지) 누락")
             continue
            
        # 주소 조합
        def make_addr(row):
            # 1. 주소 컬럼 우선
            if '주소' in row and pd.notna(row['주소']):
                return str(row['주소']).strip()
            
            # 2. Legacy fallback (시군구 + 번지)
            if '시군구' in row and '번지' in row:
                sgg = str(row['시군구']).strip()
                bunji = str(row['번지']).strip()
                
                # 서울 단순화 (서울특별시 -> 서울)
                if normalize_seoul and sgg.startswith("서울특별시"):
                    sgg = sgg.replace("서울특별시", "서울", 1)
                
                return f"{sgg} {bunji}"
            
            return ""

        df['temp_addr'] = df.apply(make_addr, axis=1)

        # 지오코딩 수행 (lat, lng가 없는 경우에만)
        if 'lat' not in df.columns or 'lng' not in df.columns:
            df['lat'] = None
            df['lng'] = None
        
        # 대상 추출 (좌표 없는 행)
        targets = df[df['lat'].isna() | df['lng'].isna()]
        
        if not targets.empty:
            log(f"  [{sheet_name}] 지오코딩 필요: {len(targets)}건")
            
            # ThreadPool로 병렬 처리
            # cache는 외부에서 주입받은 공유 객체 사용 (thread safe logic inside geocode_address)
            
            with ThreadPoolExecutor(max_workers=10) as executor:
                # Future -> index 매핑
                future_to_idx = {
                    executor.submit(geocode_address, row['temp_addr'], kakao_key, cache): idx 
                    for idx, row in targets.iterrows()
                }
                
                completed_count = 0
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    coords = future.result()
                    
                    if coords:
                        df.at[idx, 'lng'] = coords[0]
                        df.at[idx, 'lat'] = coords[1]
                    
                    completed_count += 1
                    if completed_count % autosave_every == 0 and cache_path:
                        # 주기적 캐시 저장 (메인 스레드에서만 수행 권장하지만 lock 있으니 안전)
                        with _cache_lock:
                            save_cache(cache_path, cache)
                            
        else:
            log(f"  [{sheet_name}] 모든 데이터에 좌표 존재함.")
            
        result_dfs[sheet_name] = df

    # 엑셀 저장 (업데이트된 내용 포함)
    with pd.ExcelWriter(out_xls, engine='openpyxl') as writer:
        for sname, df in result_dfs.items():
            # temp_addr 제거 후 저장
            save_df = df.drop(columns=['temp_addr'], errors='ignore')
            save_df.to_excel(writer, sheet_name=sname, index=False)
            
    # GeoJSON 생성 로직 (Lite / Detail 분리)
    # df는 좌표가 채워져 있음 (실패한건 nan)
    for sname, df in result_dfs.items():
        # 좌표 있는 것만
        valid = df.dropna(subset=['lat', 'lng'])
        if valid.empty:
            continue
            
        # 파일명 결정 (실거래_YYYYMM_TYPE)
        # infile stem: 실거래_202501
        # sheet name mapping: 아파트->apt, 연립다세대->rh, 단독다가구->sh, 오피스텔->off
        mapping = {
            "아파트": "apt", 
            "연립다세대": "rh", 
            "단독다가구": "sh", 
            "오피스텔": "off"
        }
        
        # 시트명 포함되는 키 찾기
        code = "etc"
        for k, v in mapping.items():
            if k in sname:
                code = v
                break
        
        # 출력 파일명 기본
        # clean_stem = re.sub(r"[^0-9a-zA-Z가-힣_]", "", infile.stem)
        clean_stem = infile.stem
        # e.g. 실거래_202501_apt_lite.geojson
        # e.g. 실거래_202501_apt_detail.json
        
        # ──────── Lite Aggregation ────────
        # Group by Coordinate (or Address if coords are identical)
        # Use (lat, lng) as key
        # Aggregation: 
        #   count_total
        #   count_sale (매매)
        #   count_jeonse (전세)
        #   count_monthly (월세)
        #   name (Building Name) - take mode or first
        
        lite_features = []
        detail_map = {} # "lat,lng": [ {record...}, ... ]
        
        # Iterate rows
        # To speed up, maybe groupby?
        
        # 거래유형 컬럼 확인 (매매, 전세, 월세)
        # 데이터에 '전월세구분' or '거래유형' 컬럼이 있다고 가정
        # 보통 국토부 데이터는 '전월세구분'에 '전세', '월세'가 찍히거나
        # 별도 파일일 수 있음. 여기선 하나의 파일에 매매/전월세가 섞여있을 수도 있고 아닐 수도 있음.
        # 사용자가 제공한 엑셀 컬럼을 정확히 모르므로, '전월세구분'이나 금액 컬럼으로 추정
        # 일반적인 헤더: [계약년월, 계약일, 시군구, 번지, 본번, 부번, 단지명, 전용면적, 거래금액, 층, 건축년도, ...]
        # 매매 파일이면 '거래금액', 전월세면 '보증금', '월세' 컬럼 존재
        
        # Safe getter
        def get_val(r, col, default=''):
            return r[col] if col in r else default

        for idx, row in valid.iterrows():
            lat, lng = row['lat'], row['lng']
            coord_key = f"{lat},{lng}"
            
            # Type classification
            # If '거래금액' exists and not NaN -> Sale
            # If '보증금' exists -> Jeonse/Monthly
            tx_type = '기타'
            price = 0
            deposit = 0
            monthly = 0
            
            # Simple heuristic logic
            if '거래금액' in row and pd.notna(row['거래금액']) and str(row['거래금액']).strip():
                tx_type = '매매'
                price = int(str(row['거래금액']).replace(',', ''))
            elif '보증금' in row:
                d_val = str(row['보증금']).replace(',', '')
                if d_val:
                    deposit = int(d_val)
                
                m_val = str(row.get('월세', '0')).replace(',', '')
                if m_val and int(m_val) > 0:
                    tx_type = '월세'
                    monthly = int(m_val)
                else:
                    tx_type = '전세'
            
            # Building Name
            b_name = get_val(row, '단지명') or get_val(row, '건물명') or get_val(row, '단지명/건물명')
            if not b_name:
                # 주소로 대체
                b_name = row['temp_addr']

            # Detail Record
            # Convert row to dict for JSON
            # Timestamp objects handling needed?
            rec = row.to_dict()
            # Clean up keys/values for JSON
            cleaned_rec = {}
            for k, v in rec.items():
                if k == 'temp_addr': continue
                if pd.isna(v): continue
                if k in ['lat', 'lng']: continue # already in key
                
                # Timestamp 처리 추가
                if hasattr(v, 'isoformat'):
                    v = v.isoformat()
                
                cleaned_rec[k] = v
            
            # Add custom standardized fields
            cleaned_rec['거래유형'] = tx_type
            if tx_type == '매매': cleaned_rec['거래금액'] = price
            if tx_type in ['전세', '월세']: 
                cleaned_rec['보증금'] = deposit
                cleaned_rec['월세'] = monthly
                
            if coord_key not in detail_map:
                detail_map[coord_key] = []
            
            detail_map[coord_key].append({
                "type": "Feature",
                "properties": cleaned_rec
                # Geometry is implicit in key
            })
            
        # Create Lite Features from detail_map
        for key, records in detail_map.items():
            lat_str, lng_str = key.split(',')
            lat, lng = float(lat_str), float(lng_str)
            
            # Aggregate
            count_sale = 0
            count_jeonse = 0
            count_monthly = 0
            name_candidates = []
            
            for f in records:
                p = f['properties']
                t = p.get('거래유형')
                if t == '매매': count_sale += 1
                elif t == '전세': count_jeonse += 1
                elif t == '월세': count_monthly += 1
                
                # Name collection
                n = p.get('단지명') or p.get('건물명') or p.get('단지명/건물명')
                if n: name_candidates.append(n)
            
            # Pick representative name (most common)
            rep_name = "건물"
            if name_candidates:
                rep_name = max(set(name_candidates), key=name_candidates.count)
            else:
                # Use address from first record if name missing
                # Not available directly here, but could peek records
                pass
            
            
            lite_f = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lng, lat]
                },
                "properties": {
                    "name": rep_name,
                    "count_total": len(records),
                    "count_sale": count_sale,
                    "count_jeonse": count_jeonse,
                    "count_monthly": count_monthly,
                    "coord_key": key # Link to detail
                }
            }
            lite_features.append(lite_f)

        # ──────── Export Files ────────
        version_str = time.strftime("%Y%m%d%H%M")
        
        # 실거래_202501_apt_lite.geojson
        # 실거래_202501_apt_detail.json
        
        out_lite_name = f"{clean_stem}_{code}_lite.geojson"
        out_detail_name = f"{clean_stem}_{code}_detail.json"
        
        out_lite_path = out_geo_dir / out_lite_name
        out_detail_path = out_geo_dir / out_detail_name
        
        # Save Lite
        lite_data = {
            "type": "FeatureCollection",
            "meta": {
                "version": version_str,
                "type_code": code,
                "detail_file": out_detail_name # Reference
            },
            "features": lite_features
        }
        out_lite_path.write_text(json.dumps(lite_data, ensure_ascii=False, indent=None), encoding="utf-8")
        
        # Save Detail
        # dict key: "lat,lng" -> list of features
        out_detail_path.write_text(json.dumps(detail_map, ensure_ascii=False, indent=None), encoding="utf-8")
        
        log(f"  저장 완료: {out_lite_name} (Pts={len(lite_features)}), {out_detail_name} (Total=N)")
        generated_files.append(out_lite_path)

    # ★ manifest 갱신
    write_manifest(out_geo_dir)

    return out_xls, generated_files

# -------------------------------------------------------------------------
# 디렉터리 배치 처리
# -------------------------------------------------------------------------

def run_batch(
    directory: Path,
    kakao_key: str,
    cooldown: float = 0.2,
    include_sheets: list[str] | None = None,
    normalize_seoul: bool = True,
    recursive: bool = False,
    autosave_every: int = 50,
):
    directory = Path(directory)
    if not directory.exists():
        log(f"폴더가 없습니다: {directory}")
        return

    # 캐시 로드
    cache_path = directory / CACHE_FILE_NAME
    cache = load_cache(cache_path)
    log(f"캐시 로드: {len(cache)}건")

    # 대상 파일 찾기
    files = []
    if recursive:
        files.extend(directory.rglob("*.xlsx"))
        files.extend(directory.rglob("*.xls"))
    else:
        files.extend(directory.glob("*.xlsx"))
        files.extend(directory.glob("*.xls"))
    
    # 제외할 패턴 (_geocoded, ~$ 등)
    target_files = []
    for f in files:
        if f.name.startswith("~$") or "_geocoded" in f.name:
            continue
        target_files.append(f)
        
    log(f"처리 대상 파일: {len(target_files)}개")

    for f in target_files:
        process_excel_file(
            infile=f,
            kakao_key=kakao_key,
            cooldown=cooldown,
            include_sheets=include_sheets,
            normalize_seoul=normalize_seoul,
            cache=cache,
            cache_path=cache_path,
            autosave_every=autosave_every,
        )

    # 배치 종료 시 최종 캐시 저장
    save_cache(cache_path, cache)
    log(f"캐시 저장 완료: {cache_path.name} (entries={len(cache)})")

def write_manifest(geojson_dir: Path):
    """
    data/YYYY/geojson/*.geojson 전체를 스캔하여
    data/manifest.json 하나로 갱신 (연도 누적)
    """
    data_root = geojson_dir.parent.parent  # .../data
    manifest_path = data_root / "manifest.json"
    
    # data/<YYYY>/geojson/**/*.geojson 전부
    items = []
    
    # 주택유형 코드 매핑 (라벨용)
    code_label = {
        "apt": "아파트",
        "rh": "빌라",
        "sh": "주택",
        "off": "오피",
        "etc": "기타"
    }

    # 1. 202x, 201x 등 연도 폴더 찾기
    for year_dir in sorted(data_root.iterdir()):
        if not year_dir.is_dir() or not re.fullmatch(r"\d{4}", year_dir.name):
            continue
        
        gj_dir = year_dir / "geojson"
        if not gj_dir.is_dir():
            continue
            
        # 파일명 패턴: 실거래_YYYYMM_TYPE_lite.geojson 만 찾아서 매니페스트에 등록
        for p in sorted(gj_dir.glob("*_lite.geojson")):
            # 날짜 추출
            # 예: 실거래_202501_apt_lite.geojson
            m = re.search(r"(\d{6})_([a-z]+)_lite", p.name)
            if m:
                ym = m.group(1) # 202501
                tcode = m.group(2) # apt
                
                ym_dot = f"{ym[:4]}.{ym[4:6]}"
                t_label = code_label.get(tcode, tcode)
                
                label = f"{ym_dot} {t_label}"
                
                # server root relative path (data/...)
                # p is absolute. data_root is absolute.
                try:
                    rel_path = p.relative_to(data_root) # 2025/geojson/...
                    # Web path needs ./ prefix sometimes or just relative
                    web_path = "./" + str(rel_path).replace("\\", "/")
                    
                    detail_path = web_path.replace("_lite.geojson", "_detail.json")
                    
                    items.append({
                        "path": web_path, 
                        "detail_path": detail_path,
                        "label": label,
                        "year": ym[:4],
                        "month": ym[4:6],
                        "type": tcode
                    })
                except ValueError:
                    continue
    
    # 역순 정렬 (최신순)
    items.sort(key=lambda x: x['year'] + x['month'], reverse=True)
    
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    
    log(f"Manifest 업데이트 완료: {len(items)}건")

# -------------------------------------------------------------------------
# 실행 진입점
# -------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--directory", required=True, help="엑셀 파일이 있는 폴더 경로 (예: data/2025)")
    parser.add_argument("--key", help="카카오 API 키 (미입력 시 환경변수 or Keyring)")
    
    args = parser.parse_args()
    
    # Key
    if args.key:
        k_key = args.key
    else:
        try:
            k_key = get_kakao_key()
        except:
            log("API 키가 없습니다. 실행 불가.")
            sys.exit(1)
            
    run_batch(args.directory, k_key, recursive=False)

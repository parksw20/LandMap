import pandas as pd
import numpy as np
import re
from pathlib import Path

class ExcelParser:
    def __init__(self, type_map):
        self.type_map = type_map

    def parse_file(self, file_path):
        yyyymm = str(file_path.stem.split('_')[1])
        try:
            xls = pd.ExcelFile(file_path, engine='openpyxl')
        except Exception as e:
            print(f"      (!) 엑셀 파일 열기 실패: {e}")
            return pd.DataFrame()
            
        file_dfs = []
        for sn in xls.sheet_names:
            try:
                # 시트명으로 유형 판별 (오피/상가/토지/분양/공장을 아파트·주택보다 먼저 검사)
                snl = sn.lower()
                h_type = 'unknown'
                if any(k in snl for k in ['off', '오피']): h_type = 'off'
                elif any(k in snl for k in ['nrg', '상가', '상업', '업무']): h_type = 'nrg'
                elif any(k in snl for k in ['land', '토지']): h_type = 'land'
                elif any(k in snl for k in ['silv', '분양', '입주']): h_type = 'silv'
                elif any(k in snl for k in ['indu', '공장', '창고', '산업']): h_type = 'indu'
                elif any(k in snl for k in ['apt', '아파트']): h_type = 'apt'
                elif any(k in snl for k in ['rh', '연립', '다세대', '빌라']): h_type = 'rh'
                elif any(k in snl for k in ['sh', '단독', '다가구', '주택']): h_type = 'sh'
                if h_type == 'unknown': h_type = 'apt'

                is_sale_sheet = any(k in sn for k in ['매매', '분양'])

                # 헤더 찾기
                temp_df = pd.read_excel(xls, sheet_name=sn, header=None, nrows=20)
                header_idx = 0
                for idx, row in temp_df.iterrows():
                    row_str = "".join([str(x) for x in row.values])
                    if any(k in row_str for k in ['시도', '시군구', '거래금액', '보증금']):
                        header_idx = idx
                        break
                
                df = pd.read_excel(xls, sheet_name=sn, skiprows=header_idx)
                if df.empty: continue

                cols = df.columns.tolist()
                def find_col(kws, exclude=None):
                    for kw in kws:
                        for c in cols:
                            c_str = str(c).replace(" ", "").replace("\n", "")
                            if kw == c_str: return c
                            if kw in c_str:
                                if exclude and any(ex in c_str for ex in exclude): continue
                                return c
                    return None
                
                price_kws = ['거래금액', '금액'] if is_sale_sheet else ['보증금', '전세금']
                
                m = {
                    'address': find_col(['주소']),
                    'name': find_col(['단지명', '건물명', '명칭']),
                    'sido': find_col(['시도', '시/도']),
                    'gungu': find_col(['시군구', '군/구', '구/시']),
                    'dong': find_col(['법정동']),
                    'jibeon': find_col(['지번', '번지']),
                    'price': find_col(price_kws),
                    'rent': find_col(['월세', '임대료']),
                    'area': find_col(['전용면적', '면적']),
                    'land': find_col(['대지면적', '대지권']),
                    'floor': find_col(['층']),
                    'bdong': find_col(['동'], exclude=['법정동', '행정동', '동명', '시도', '시군구']), 
                    'date': find_col(['계약일', '일자']),
                    'period': find_col(['임차기간']),
                    'renew': find_col(['갱신', '요구']),
                    'p_dep': find_col(['종전', '기존']),
                    'p_rent': find_col(['기존월세', '종전임대료']),
                    'tx_div': find_col(['전월세구분', '구분'])
                }

                def to_int(val):
                    if pd.isna(val): return 0
                    try:
                        clean_val = re.sub(r'[^0-9.]', '', str(val))
                        return int(float(clean_val)) if clean_val else 0
                    except: return 0

                def get_tx_type(row):
                    if is_sale_sheet: return '매매'
                    if m['tx_div']:
                        val = str(row[m['tx_div']])
                        if '전세' in val: return '전세'
                        if '월세' in val: return '월세'
                    if m['rent'] and to_int(row[m['rent']]) > 0: return '월세'
                    return '전세'

                res_list = []
                for _, row in df.iterrows():
                    # 주소 정보 정제
                    sido_v = str(row[m['sido']]).strip() if m['sido'] and pd.notna(row[m['sido']]) else ""
                    gungu_v = str(row[m['gungu']]).strip() if m['gungu'] and pd.notna(row[m['gungu']]) else ""
                    dong_v = str(row[m['dong']]).strip() if m['dong'] and pd.notna(row[m['dong']]) else ""
                    jibeon_v = str(row[m['jibeon']]).strip() if m['jibeon'] and pd.notna(row[m['jibeon']]) else ""
                    
                    # 시군구에 시도 정보가 포함된 경우(예: "서울특별시 강남구") 처리
                    if sido_v == "" and len(gungu_v.split()) > 1:
                        parts = gungu_v.split()
                        sido_v = parts[0]
                        gungu_v = " ".join(parts[1:])

                    # 카드 표시용 원본 지번 (마스킹 '*' 포함 그대로 보존)
                    raw_jibun = jibeon_v

                    # 마스킹된 지번(예: '3*', '1**')은 지오코딩 실패(탈락)나 구 중심 오좌표를 유발
                    # → 주소에서 제외하고 동 단위로 지오코딩한다 (단독/다가구 개인정보 마스킹 대응)
                    if '*' in jibeon_v:
                        jibeon_v = ""

                    full_addr = " ".join([p for p in [sido_v, gungu_v, dong_v, jibeon_v] if p]).strip()
                    if m['address'] and pd.notna(row[m['address']]):
                        full_addr = str(row[m['address']]).strip()
                        full_addr = " ".join(t for t in full_addr.split() if '*' not in t)

                    # 번지 숫자가 전혀 없는 주소는 위치 특정 불가:
                    #  - 단독 전월세: 지번/도로명 미제공 → 주소가 '동대문구' 뿐
                    #  - 마스킹 매매: '동대문구 청량리동' (위에서 '*' 제거됨)
                    # → 법정동 canonical 주소로 통일해 매매/전월세가 같은 동 중심 그룹에 묶이게 함
                    if dong_v and not any(ch.isdigit() for ch in full_addr):
                        full_addr = " ".join([p for p in [sido_v, gungu_v, dong_v] if p]).strip()

                    if len(full_addr) < 2: continue
                    
                    raw_date = str(row[m['date']]).strip() if m['date'] and pd.notna(row[m['date']]) else ""
                    clean_date = raw_date.split(' ')[0].split('T')[0]

                    res_list.append({
                        '__address': full_addr,
                        '__name': str(row[m['name']]).strip() if m['name'] and pd.notna(row[m['name']]) else full_addr,
                        '__sido': sido_v,
                        '__gungu': gungu_v,
                        '__dong': dong_v,
                        '__jibun': raw_jibun,
                        '__tx_type': get_tx_type(row),
                        '__h_type': h_type,
                        '__ym': yyyymm,
                        '__price': to_int(row[m['price']]) if m['price'] else 0,
                        '__rent': to_int(row[m['rent']]) if m['rent'] else 0,
                        '__area': float(re.sub(r'[^0-9.]', '', str(row[m['area']]))) if m['area'] and pd.notna(row[m['area']]) else 0.0,
                        '__land': float(re.sub(r'[^0-9.]', '', str(row[m['land']]))) if m['land'] and pd.notna(row[m['land']]) else 0.0,
                        '__floor': str(row[m['floor']]).split('.')[0] if m['floor'] and pd.notna(row[m['floor']]) else "",
                        '__bdong': str(row[m['bdong']]).split('.')[0] if m['bdong'] and pd.notna(row[m['bdong']]) else "",
                        '__date': clean_date,
                        '__period': str(row[m['period']]).strip() if m['period'] and pd.notna(row[m['period']]) else "",
                        '__renew': str(row[m['renew']]).strip() if m['renew'] and pd.notna(row[m['renew']]) else "",
                        '__p_dep': to_int(row[m['p_dep']]) if m['p_dep'] else 0,
                        '__p_rent': to_int(row[m['p_rent']]) if m['p_rent'] else 0
                    })
                
                if res_list:
                    file_dfs.append(pd.DataFrame(res_list))
            except Exception as e:
                print(f"      (!) {sn} 오류: {e}")
        
        return pd.concat(file_dfs, ignore_index=True) if file_dfs else pd.DataFrame()

import pandas as pd
import json

file_path = r'C:\cli\PROJECT\부동산\data\2026\실거래_202601_v2604050105.xlsx'
xls = pd.ExcelFile(file_path)

print(f"Sheets: {xls.sheet_names}")

for sheet in xls.sheet_names:
    print(f"\n--- [{sheet}] ---")
    df = pd.read_excel(xls, sheet_name=sheet, nrows=5)
    print("Columns:", df.columns.tolist())
    # 거래유형 컬럼 확인
    type_cols = [c for c in df.columns if '유형' in c or '구분' in c]
    if type_cols:
        print("Sample values in", type_cols[0], ":", df[type_cols[0]].unique())
    print(df.head(2))

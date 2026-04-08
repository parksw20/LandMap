# address_static.py
# 목적: 서울/경기 시군구 LAWD_CD(법정동 앞 5자리) 목록을 CSV/JSON으로 저장
# 사용: python address_static.py  (동일 폴더에 CSV/JSON 생성)

from pathlib import Path
import json
import csv

# --- 서울특별시(25구) ---
SEOUL = [
    {"region_name":"서울특별시_종로구",   "LAWD_CD":"11110"},
    {"region_name":"서울특별시_중구",     "LAWD_CD":"11140"},
    {"region_name":"서울특별시_용산구",   "LAWD_CD":"11170"},
    {"region_name":"서울특별시_성동구",   "LAWD_CD":"11200"},
    {"region_name":"서울특별시_광진구",   "LAWD_CD":"11215"},
    {"region_name":"서울특별시_동대문구", "LAWD_CD":"11230"},
    {"region_name":"서울특별시_중랑구",   "LAWD_CD":"11260"},
    {"region_name":"서울특별시_성북구",   "LAWD_CD":"11290"},
    {"region_name":"서울특별시_강북구",   "LAWD_CD":"11305"},
    {"region_name":"서울특별시_도봉구",   "LAWD_CD":"11320"},
    {"region_name":"서울특별시_노원구",   "LAWD_CD":"11350"},
    {"region_name":"서울특별시_은평구",   "LAWD_CD":"11380"},
    {"region_name":"서울특별시_서대문구", "LAWD_CD":"11410"},
    {"region_name":"서울특별시_마포구",   "LAWD_CD":"11440"},
    {"region_name":"서울특별시_양천구",   "LAWD_CD":"11470"},
    {"region_name":"서울특별시_강서구",   "LAWD_CD":"11500"},
    {"region_name":"서울특별시_구로구",   "LAWD_CD":"11530"},
    {"region_name":"서울특별시_금천구",   "LAWD_CD":"11545"},
    {"region_name":"서울특별시_영등포구", "LAWD_CD":"11560"},
    {"region_name":"서울특별시_동작구",   "LAWD_CD":"11590"},
    {"region_name":"서울특별시_관악구",   "LAWD_CD":"11620"},
    {"region_name":"서울특별시_서초구",   "LAWD_CD":"11650"},
    {"region_name":"서울특별시_강남구",   "LAWD_CD":"11680"},
    {"region_name":"서울특별시_송파구",   "LAWD_CD":"11710"},
    {"region_name":"서울특별시_강동구",   "LAWD_CD":"11740"},
]

# --- 경기도(31 시·군) + 구 설치 시군은 구 단위 코드 포함 ---
GYEONGGI = [
    # 수원시(4구)
    {"region_name":"경기도_수원시_장안구", "LAWD_CD":"41111"},
    {"region_name":"경기도_수원시_권선구", "LAWD_CD":"41113"},
    {"region_name":"경기도_수원시_팔달구", "LAWD_CD":"41115"},
    {"region_name":"경기도_수원시_영통구", "LAWD_CD":"41117"},
    # 성남시(3구)
    {"region_name":"경기도_성남시_수정구", "LAWD_CD":"41131"},
    {"region_name":"경기도_성남시_중원구", "LAWD_CD":"41133"},
    {"region_name":"경기도_성남시_분당구", "LAWD_CD":"41135"},
    # 의정부시
    {"region_name":"경기도_의정부시", "LAWD_CD":"41150"},
    # 안양시(2구)
    {"region_name":"경기도_안양시_만안구", "LAWD_CD":"41171"},
    {"region_name":"경기도_안양시_동안구", "LAWD_CD":"41173"},
    # 부천시(단일: 2016년 구 폐지, 시 단일 코드)
    {"region_name":"경기도_부천시", "LAWD_CD":"41190"},
    # 광명시
    {"region_name":"경기도_광명시", "LAWD_CD":"41210"},
    # 평택시
    {"region_name":"경기도_평택시", "LAWD_CD":"41220"},
    # 동두천시
    {"region_name":"경기도_동두천시", "LAWD_CD":"41250"},
    # 안산시(2구)
    {"region_name":"경기도_안산시_상록구", "LAWD_CD":"41271"},
    {"region_name":"경기도_안산시_단원구", "LAWD_CD":"41273"},
    # 고양시(3구)
    {"region_name":"경기도_고양시_덕양구",   "LAWD_CD":"41281"},
    {"region_name":"경기도_고양시_일산동구", "LAWD_CD":"41285"},
    {"region_name":"경기도_고양시_일산서구", "LAWD_CD":"41287"},
    # 과천시
    {"region_name":"경기도_과천시", "LAWD_CD":"41290"},
    # 구리시
    {"region_name":"경기도_구리시", "LAWD_CD":"41310"},
    # 남양주시
    {"region_name":"경기도_남양주시", "LAWD_CD":"41360"},
    # 오산시
    {"region_name":"경기도_오산시", "LAWD_CD":"41370"},
    # 시흥시
    {"region_name":"경기도_시흥시", "LAWD_CD":"41390"},
    # 군포시
    {"region_name":"경기도_군포시", "LAWD_CD":"41410"},
    # 의왕시
    {"region_name":"경기도_의왕시", "LAWD_CD":"41430"},
    # 하남시
    {"region_name":"경기도_하남시", "LAWD_CD":"41450"},
    # 용인시(3구)
    {"region_name":"경기도_용인시_처인구", "LAWD_CD":"41461"},
    {"region_name":"경기도_용인시_기흥구", "LAWD_CD":"41463"},
    {"region_name":"경기도_용인시_수지구", "LAWD_CD":"41465"},
    # 파주시
    {"region_name":"경기도_파주시", "LAWD_CD":"41480"},
    # 이천시
    {"region_name":"경기도_이천시", "LAWD_CD":"41500"},
    # 안성시
    {"region_name":"경기도_안성시", "LAWD_CD":"41550"},
    # 김포시
    {"region_name":"경기도_김포시", "LAWD_CD":"41570"},
    # 화성시
    {"region_name":"경기도_화성시", "LAWD_CD":"41590"},
    # 광주시
    {"region_name":"경기도_광주시", "LAWD_CD":"41610"},
    # 양주시
    {"region_name":"경기도_양주시", "LAWD_CD":"41630"},
    # 포천시
    {"region_name":"경기도_포천시", "LAWD_CD":"41650"},
    # 여주시
    {"region_name":"경기도_여주시", "LAWD_CD":"41670"},
    # 연천군
    {"region_name":"경기도_연천군", "LAWD_CD":"41800"},
    # 가평군
    {"region_name":"경기도_가평군", "LAWD_CD":"41820"},
    # 양평군
    {"region_name":"경기도_양평군", "LAWD_CD":"41830"},
]

DATA = SEOUL + GYEONGGI

def save_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["region_name","LAWD_CD"])
        w.writeheader()
        for r in rows:
            w.writerow({"region_name": r["region_name"], "LAWD_CD": r["LAWD_CD"]})

def save_json(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

def main():
    csv_path  = Path("LAWD_서울_경기.csv")
    save_csv(csv_path, DATA)
    json_path = Path("LAWD_서울_경기.json") 
    # save_json(json_path, DATA) # json 추출 필요 시 사용
    print(f"[✓] 저장 완료: {len(DATA)}개")
    print(f"    CSV : {csv_path.resolve()}")
    #print(f"    JSON: {json_path.resolve()}")

if __name__ == "__main__":
    main()

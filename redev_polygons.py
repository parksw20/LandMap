# redev_polygons.py — 서울시 의제처리구역 SHP에서 정비구역 경계 폴리곤 추출
#
# 입력: UPIS_C_UQ181 SHP (data.go.kr '의제처리구역 위치정보', LCLAS_CL=UQ1200 정비구역 계열)
# 매칭: data/redev_zones.json 의 472개 구역과 구역명 정규화 매칭
#        1차 정확 매칭 → 2차 포함관계 매칭(구역 지오코딩 좌표와 중심점 2km 이내 검증)
# 출력: data/redev_polygons.json  { "구|구역명": [ [ [lng,lat], ... ], ... ] }
#
# 실행: python redev_polygons.py [SHP경로(확장자 제외)]

import json
import math
import re
import sys
from pathlib import Path

import shapefile
from pyproj import CRS, Transformer

ROOT = Path(__file__).parent
ZONES_PATH = ROOT / "data" / "redev_zones.json"
OUT_PATH = ROOT / "data" / "redev_polygons.json"

DEFAULT_SHP = r"C:\Users\user\Downloads\UQ181_의제처리구역_202602\shp파일\UPIS_C_UQ181"

SUFFIXES = [
    '재정비촉진구역', '주택정비형재개발정비구역', '도시정비형재개발정비구역',
    '주택재개발정비구역', '주택재건축정비구역', '도시환경정비구역',
    '재개발정비구역', '재건축정비구역', '정비사업', '정비구역',
    '재개발사업', '재건축사업', '재개발', '재건축', '도시환경',
    '아파트', '주택', '구역', '지구', '사업', '일대', '번지',
]


def norm(s: str) -> str:
    s = re.sub(r'\s+', '', str(s))
    s = re.sub(r'제(\d)', r'\1', s)
    for suf in SUFFIXES:
        s = s.replace(suf, '')
    return s


def dist_km(a, b):
    """[lng,lat] 두 점 간 대략적 거리(km)"""
    dx = (a[0] - b[0]) * 88.8  # 서울 위도에서 경도 1도 ≈ 88.8km
    dy = (a[1] - b[1]) * 111.0
    return math.hypot(dx, dy)


def main():
    shp_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SHP
    zones = json.load(open(ZONES_PATH, encoding='utf-8'))

    sf = shapefile.Reader(shp_path, encoding='cp949')
    flds = [f[0] for f in sf.fields[1:]]
    crs = CRS.from_wkt(open(shp_path + '.prj', encoding='utf-8').read())
    tr = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)

    # 정비구역 계열(UQ1200)만 추출 + 좌표 변환
    cands = []  # (norm_name, rings, centroid)
    for sr in sf.iterShapeRecords():
        rec = dict(zip(flds, sr.record))
        if rec.get('LCLAS_CL') != 'UQ1200':
            continue
        name = norm(rec.get('DGM_NM', ''))
        if not name:
            continue
        shape = sr.shape
        pts = shape.points
        parts = list(shape.parts) + [len(pts)]
        rings = []
        for i in range(len(parts) - 1):
            ring = pts[parts[i]:parts[i + 1]]
            lngs, lats = tr.transform([p[0] for p in ring], [p[1] for p in ring])
            rings.append([[round(x, 6), round(y, 6)] for x, y in zip(lngs, lats)])
        if not rings:
            continue
        allp = [p for r in rings for p in r]
        centroid = [sum(p[0] for p in allp) / len(allp), sum(p[1] for p in allp) / len(allp)]
        cands.append((name, rings, centroid))

    print(f"SHP 정비구역 계열: {len(cands)}개")

    # 이름 인덱스
    by_name = {}
    for i, (n, _, _) in enumerate(cands):
        by_name.setdefault(n, []).append(i)

    out, exact, fuzzy = {}, 0, 0
    for z in zones:
        zn = norm(z['name'])
        if not zn:
            continue
        key = f"{z['district']}|{z['name']}"
        zc = z['coords']

        # 1차: 정확 매칭 (동명 구역 대비 중심점 최근접 선택)
        idxs = by_name.get(zn, [])
        if idxs:
            best = min(idxs, key=lambda i: dist_km(cands[i][2], zc))
            if dist_km(cands[best][2], zc) < 3.0:
                out[key] = cands[best][1]
                exact += 1
                continue

        # 2차: 포함관계 매칭 + 거리 검증
        if len(zn) >= 3:
            pool = [i for i, (n, _, _) in enumerate(cands)
                    if (zn in n or n in zn) and dist_km(cands[i][2], zc) < 2.0]
            if pool:
                best = min(pool, key=lambda i: dist_km(cands[i][2], zc))
                out[key] = cands[best][1]
                fuzzy += 1

    json.dump(out, open(OUT_PATH, 'w', encoding='utf-8'), ensure_ascii=False,
              separators=(',', ':'))
    size_mb = OUT_PATH.stat().st_size / 1e6
    print(f"[완료] 매칭 {len(out)}/{len(zones)} (정확 {exact} + 유사 {fuzzy}) → {OUT_PATH} ({size_mb:.1f}MB)")


if __name__ == "__main__":
    main()

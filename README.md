# LandMap — 부동산 실거래 시각화

국토교통부 실거래 데이터를 카카오 지도 위에 시각화하는 웹앱.
공개 사이트: **https://parksw20.github.io/LandMap/data/**

파이프라인은 **로컬 배치(수집·가공) → 정적 JSON → GitHub Pages → 브라우저**.
배포된 웹앱은 API를 호출하지 않고 미리 만들어둔 정적 JSON만 읽는다.

---

## 빠른 시작

```bat
실행.bat
```

- 지도: http://localhost:8080/index.html
- 관리 콘솔: 지도 우하단 **⚙** 버튼 → 또는 http://localhost:8080/panel

`실행.bat`이 `scripts/panel.py`(정적 서버 + 원클릭 실행 API)를 띄운다.
로컬 서버 관리는 `C:\CLI\PROJECT\_server-manager`(부동산 카드)로도 가능하다.

---

## 데이터 갱신 (관리 콘솔 버튼)

⚙ 관리 콘솔에서 버튼만 누르면 된다. 각 작업은 진행 단계가 실시간 표시된다.

| 버튼 | 하는 일 | 언제 |
|---|---|---|
| 📅 **월간 실거래 갱신** | 이번 달 다운로드 → 가공 → 커밋·푸시 | 매달 한 번 |
| 📥 **밀린 달 채우기** | 빠진 달을 현재월까지 자동 탐지·수집 | 며칠/몇 달 걸렀을 때 |
| 🔄 **전체 재생성** | 재다운로드 없이 기존 엑셀로 전 기간 재가공 | 데이터 구조·로직 변경 시 |
| 🏢 **건축물대장 이어받기** | 남은 법정동 수집(쿼터 한도까지) | 대장 수집 이어서 |

중간에 멈춰도 안전하다. 대장은 완전 이어받기(25동마다 저장), 나머지는 다시 누르면 처음부터 깨끗이 재실행(커밋은 성공 후에만).

---

## 폴더 구조

```
부동산/
├─ 실행.bat              지도 + 관리 콘솔 실행 (평소 이것만)
├─ run_ledger.bat        건축물대장 자동수집 (예약작업이 호출)
├─ LAWD_서울_경기.csv    지역 코드 (land.py 입력)
├─ README.md
├─ data/                 ★ 배포되는 정적 자산 (지도·JSON·app.js)
│  ├─ index.html · app.js · styles.css
│  ├─ panel.html         관리 콘솔 (로컬 전용, 미배포)
│  ├─ hierarchy/         월×유형별 실거래 요약·상세 JSON
│  ├─ areas/             전 평형 목록
│  ├─ *.json             단지 속성·정비구역·검색인덱스 등
│  └─ *_cache/           수집 캐시 (재실행 이어받기용)
├─ scripts/              ★ 수집·가공 파이썬 (아래 참조)
└─ _archive/             미사용/대체된 스크립트 (복구 가능)
```

## scripts/ — 파이프라인

**수집 (외부 API 호출)**
- `land.py` — 국토부 RTMS 월별 실거래 → 엑셀
- `geo_cache.py` — 카카오 지오코딩 (주소→좌표)
- `match_parcels.py` (+`match_buildings.py`) — VWorld 연속지적도로 마스킹 단독 지번 복원

**가공 (엑셀 → 정적 JSON)**
- `data_manager.py` — 총괄. 파싱·지오코딩·집계 실행 (`-m YYYYMM` 특정월 / `-r` 전체 재생성)
- `excel_parser.py`, `hierarchy_builder.py` — 파싱·계층 집계

**보강 (단지 속성·부가 데이터)**
- `apt_info.py` 세대·주차·연식 · `supply_area.py` 공급면적 · `bldg_ratio.py` 용적률·건폐율
- `bldg_ledger.py` 건축물대장(구축 공급면적·용도) · `no_deal_apts.py` 거래없음 단지
- `complex_areas.py` 전 평형 · `bjd_codes.py` 법정동코드 · `redev_polygons.py`/`redev_manager.py` 정비구역

**실행/서버**
- `panel.py` — 관리 콘솔 서버 (정적 서빙 + 실행 API)
- `update_monthly.py` — 원클릭 갱신 파이프라인 (`--backfill` / `--rebuild`)
- `make_config.py`, `make_pages_key.py` — 설정 파일 생성 (초기 세팅용)

> ⚠️ 스크립트끼리 서로 import하고 `data/`를 프로젝트 루트 기준으로 찾는다.
> 개별 실행 시 **프로젝트 루트에서** `python scripts/<이름>.py` 로 실행할 것.

---

## 자동화 (Windows 작업 스케줄러)

- **부동산_건축물대장수집** — 매일 00:30, `run_ledger.bat` 실행. 남은 대장을 쿼터만큼 수집·커밋.
- **부동산 파이썬** — 매월 말, 실거래 다운로드. (관리 콘솔 "월간 갱신" 버튼이 이를 대체)

---

## 키 (keyring)

```python
import keyring
keyring.set_password('data_go_kr','parksw20','<공공데이터포털 키>')
keyring.set_password('kakao','api_key','<카카오 REST 키>')
```
`config.local.js`(API 키 포함)는 `make_config.py`가 생성하며 커밋하지 않는다(.gitignore).

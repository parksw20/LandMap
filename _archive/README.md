# _archive — 더 이상 상시 사용하지 않는 스크립트

루트를 깔끔히 유지하려고 옮겨둔 것들입니다. 삭제가 아니라 이동이라 언제든 되돌릴 수 있습니다.
(핵심 파이프라인이 import하지 않는 것만 옮겼습니다.)

## 일회성 / 디버그 스크립트 (2025-04, 참조 없음)
- `gen_samples.py` — 샘플 데이터 생성
- `check_cache_keys.py` — 캐시 키 점검
- `debug_gen.py` — 가공 디버그
- `inspect_excel.py` — 엑셀 구조 확인
- `fix_cache.py` — 캐시 일회성 보정

## 대시보드로 대체된 수동 실행 배치
- `데이터추가.bat` — `python land.py --prev` (이전달 다운로드)
- `년월추가.bat` — `python data_manager.py` (가공)
  → 이제 지도 우하단 ⚙ **관리 콘솔**의 버튼(월간 갱신 / 밀린 달 채우기 / 전체 재생성)이 대신합니다.

## 일회성 오케스트레이션
- `finish_all.ps1` — 건축물대장 초기 수집용. 지금은 `run_ledger.bat` + 예약작업(매일 00:30)이 담당.

---
되돌리려면: `git mv _archive/<파일> ./`

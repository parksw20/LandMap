@echo off
REM 건축물대장 보완 수집 — 일일 쿼터 회복 후 자동 실행용 (Windows 작업 스케줄러)
REM 매일 00:30 실행: 그날치 쿼터만큼 수집(~300-400동) 후 429에서 안전 중단.
REM 남은 동이 0이 될 때까지 며칠에 걸쳐 자동으로 이어받는다.
cd /d "%~dp0"
echo [%date% %time%] 건축물대장 수집 시작 >> ledger_auto.log
python -X utf8 bldg_ledger.py >> ledger_auto.log 2>&1
echo [%date% %time%] 수집 종료 (exit %errorlevel%) >> ledger_auto.log

REM --- 진행분 자동 커밋/푸시 (변경 있을 때만) ---
git add data/ledger_cache/area.json data/ledger_cache/title.json data/supply_area.json data/bldg_ratio.json
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Data: 건축물대장 수집 자동 진행분 (스케줄러)" >> ledger_auto.log 2>&1
  git push origin master >> ledger_auto.log 2>&1
  echo [%date% %time%] 커밋/푸시 완료 >> ledger_auto.log
) else (
  echo [%date% %time%] 변경 없음 - 수집 완료되었거나 쿼터 미회복 >> ledger_auto.log
)

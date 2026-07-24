@echo off
REM 건축물대장 보완 수집 — 일일 쿼터 회복 후 자동 실행용 (Windows 작업 스케줄러)
REM 쿼터가 또 소진되면 스크립트가 안전하게 중단하고 진행분을 저장한다.
cd /d "%~dp0"
echo [%date% %time%] 건축물대장 수집 시작 >> ledger_auto.log
python -X utf8 bldg_ledger.py >> ledger_auto.log 2>&1
echo [%date% %time%] 종료 (exit %errorlevel%) >> ledger_auto.log

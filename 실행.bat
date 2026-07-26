@echo off
:: UTF-8 코드 페이지로 변경
chcp 65001 > nul

title RealEstate Map Server
cd /d "%~dp0"

:: 기존 8080 서버(옛 http.server 포함) 정리 — IPv6 잔류 서버가 /panel을 가로채는 것 방지
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8080 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1

echo 부동산 실거래 시각화 + 관리 서버를 시작합니다...
echo 지도:      http://localhost:8080/index.html
echo 관리콘솔:  http://localhost:8080/panel
:: panel.py = 정적 서버 + 원클릭 실행 API (기존 http.server 대체)
start /min "RealEstateServer" python -X utf8 panel.py
timeout /t 2 /nobreak > nul
start http://localhost:8080/index.html

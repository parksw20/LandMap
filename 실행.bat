@echo off
:: UTF-8 코드 페이지로 변경
chcp 65001 > nul

title RealEstate Map Server
cd /d "%~dp0"
echo 부동산 실거래 시각화 + 관리 서버를 시작합니다...
echo 지도:      http://localhost:8080/index.html
echo 관리콘솔:  http://localhost:8080/panel
:: panel.py = 정적 서버 + 원클릭 실행 API (기존 http.server 대체)
start /min "RealEstateServer" python -X utf8 panel.py
timeout /t 2 /nobreak > nul
start http://localhost:8080/index.html

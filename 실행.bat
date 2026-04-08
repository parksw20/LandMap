@echo off
:: UTF-8 코드 페이지로 변경
chcp 65001 > nul

title RealEstate Map Server
cd /d "%~dp0data"
echo 부동산 실거래 시각화 서버를 시작합니다...
echo 주소: http://localhost:8080/index.html
start /min "RealEstateServer" python -m http.server 8080
timeout /t 2 /nobreak > nul
start http://localhost:8080/index.html
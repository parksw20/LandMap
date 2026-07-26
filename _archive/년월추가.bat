@echo off
:: UTF-8 코드 페이지로 변경
chcp 65001 > nul

title RealEstate Map Server
echo manifest.json에 누락된 데이터 리스트를 추가합니다. 

python data_manager.py
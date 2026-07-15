@echo off
:: UTF-8 코드 페이지로 변경
chcp 65001 > nul

title RealEstate Map Server
echo 데이터 추가합니다. 

:: 인자 활용 사용 예시
:: 현재월만: python land.py -n → x=0, y=1 이므로 “현재월” 1개월만 추출
:: 이전달만(과거 호환): python land.py --prev → 이전달 1개월
:: 6개월 전부터 3개월치(예: 오늘이 10월이면 4·5·6월): python land.py -n 6 3
:: 특정 한 달만: python land.py -m 202504

python land.py --prev 
pause
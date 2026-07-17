# make_pages_key.py — 기존 VWorld 키(keyring 'v-world'/'parksw20')를
# GitHub Pages용 config.pages.js에 기록 (공개 저장소에 커밋될 파일임을 인지하고 실행)
#
# 실행: python make_pages_key.py

import keyring
from pathlib import Path

key = keyring.get_password("v-world", "parksw20")
if not key or len(key) < 10:
    print("(!) keyring에 VWorld 키가 없습니다")
    raise SystemExit(1)

out = Path(__file__).parent / "data" / "config.pages.js"
out.write_text(
    "// GitHub Pages 배포용 VWorld 키 (공개 - 사용자 선택으로 로컬 키와 동일 키 사용)\n"
    "// domain 파라미터는 키 등록 도메인(localhost)과 일치해야 통과\n"
    "if (!window.VWORLD_KEY) {\n"
    f"    window.VWORLD_KEY = '{key}';\n"
    "    window.VWORLD_DOMAIN = 'localhost';\n"
    "}\n",
    encoding="utf-8",
)
print(f"[OK] {out} 생성 완료 - 커밋하면 Pages(폰)에서 VWorld 기능이 활성화됩니다")

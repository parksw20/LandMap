# make_config.py — 브라우저용 로컬 설정 파일 생성 (git 미포함)
#
# keyring에 저장된 VWorld 인증키를 data/config.local.js 로 내보낸다.
# 실행: python make_config.py  (키 변경/재발급 시 한 번씩)
#
# 주의: data/config.local.js 는 .gitignore 대상 — 절대 커밋하지 말 것.

import keyring
from pathlib import Path

OUT = Path(__file__).parent / "data" / "config.local.js"

key = keyring.get_password("v-world", "parksw20")
if not key or len(key) < 10:
    print("(!) VWorld 키가 없거나 잘못됨:")
    print("    python -c \"import keyring; keyring.set_password('v-world','parksw20','발급키')\"")
    raise SystemExit(1)

OUT.write_text(f"// 로컬 전용 설정 (git 미포함) — make_config.py 로 생성됨\n"
               f"window.VWORLD_KEY = '{key}';\n", encoding="utf-8")
print(f"[OK] {OUT} 생성 완료")

# (선택) GitHub Pages 배포용 공개 키 — parksw20.github.io 도메인으로 발급받은 키를
#   python -c "import keyring; keyring.set_password('v-world','parksw20-pages','발급키')"
# 로 저장하면 config.pages.js(커밋되는 파일)를 생성해 Pages에서도 VWorld 기능 동작.
pages_key = keyring.get_password("v-world", "parksw20-pages")
PAGES_OUT = Path(__file__).parent / "data" / "config.pages.js"
if pages_key and len(pages_key) > 10:
    PAGES_OUT.write_text(
        "// GitHub Pages 배포용 VWorld 공개 키 (커밋되는 파일 — 로컬 키와 별개)\n"
        "// 갱신: make_config.py  (keyring 'v-world'/'parksw20-pages')\n"
        "if (!window.VWORLD_KEY) {\n"
        f"    window.VWORLD_KEY = '{pages_key}';\n"
        "    window.VWORLD_DOMAIN = 'parksw20.github.io';\n"
        "}\n", encoding="utf-8")
    print(f"[OK] {PAGES_OUT} 생성 완료 (Pages 공개 키 포함, 커밋 필요)")
else:
    print("[i] Pages 공개 키 없음: config.pages.js는 현재 no-op 상태 유지")

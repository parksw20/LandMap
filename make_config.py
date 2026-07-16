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

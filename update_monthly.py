# update_monthly.py — 월간 실거래 갱신 원클릭 파이프라인
#
#   ① land.py -n         현재월 실거래 다운로드 (국토부 RTMS)
#   ② 같은 달 구버전 정리  실거래_YYYYMM_* 중 최신 1개만 남김 (중복 가공 방지)
#   ③ data_manager.py -m  해당 월만 재가공 → hierarchy 정적 JSON 갱신
#   ④ git commit + push   가공 결과 배포 (엑셀은 .gitignore라 제외됨)
#
# 대시보드 '월간 갱신' 버튼(panel.py)이 이 스크립트를 호출한다.
# 단독 실행: python update_monthly.py  [YYYYMM]

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
PY = [sys.executable, "-X", "utf8"]


def run(cmd, label):
    print(f"\n===== {label} =====", flush=True)
    print("> " + " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    print(f"(exit {r.returncode})", flush=True)
    return r.returncode


def prune_old_versions(month):
    """같은 달의 구버전 엑셀 제거 — data_manager가 중복 처리하지 않도록 최신 1개만."""
    year = month[:4]
    d = ROOT / "data" / year
    if not d.exists():
        return
    files = sorted(d.glob(f"실거래_{month}_*.xlsx"))
    if len(files) <= 1:
        return
    files.sort(key=lambda f: f.stat().st_mtime)   # 오래된 → 최신
    for f in files[:-1]:
        print(f"  구버전 제거: {f.name}", flush=True)
        f.unlink()


def main():
    month = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m")
    print(f"[월간 갱신] 대상 월 {month}", flush=True)

    if run(PY + ["land.py", "-n"], "① 실거래 다운로드") != 0:
        print("[!] 다운로드 실패 — 중단", flush=True)
        return
    prune_old_versions(month)

    if run(PY + ["data_manager.py", "-m", month], "③ 데이터 가공") != 0:
        print("[!] 가공 실패 — 커밋 생략", flush=True)
        return

    # ④ 커밋/푸시 (엑셀 제외, 가공 산출물만 — .gitignore가 처리)
    print("\n===== ④ 커밋 / 푸시 =====", flush=True)
    subprocess.run(["git", "add", "-A", "data/"], cwd=ROOT)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if diff.returncode == 0:
        print("변경 없음 — 커밋 생략", flush=True)
        return
    subprocess.run(["git", "commit", "-m", f"Data: {month} 월간 실거래 갱신 (자동)"], cwd=ROOT)
    push = subprocess.run(["git", "push", "origin", "master"], cwd=ROOT)
    print(f"[완료] {month} 갱신 배포" + ("" if push.returncode == 0 else " (푸시 실패 — 수동 확인)"), flush=True)


if __name__ == "__main__":
    main()

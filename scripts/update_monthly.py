# update_monthly.py — 실거래 데이터 갱신 파이프라인 (원클릭)
#
# 모드:
#   (기본)        이번 달만: land.py -n → 구버전정리 → data_manager -m → 커밋/푸시
#   --backfill    밀린 달 채우기: manifest에 빠진 달을 현재월까지 받아 가공 → 커밋/푸시
#   --rebuild     전체 재생성: 재다운로드 없이 기존 엑셀로 data_manager -r → 커밋/푸시
#                 (가공 로직/JSON 구조가 바뀌었을 때)
#
# 대시보드(panel.py)의 세 버튼이 각각 이 모드를 호출한다.
# 단독 실행: python update_monthly.py [--backfill|--rebuild] [YYYYMM]

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PY = [sys.executable, "-X", "utf8"]


def run(cmd, label):
    print(f"\n===== {label} =====", flush=True)
    print("> " + " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    print(f"(exit {r.returncode})", flush=True)
    return r.returncode


def current_month():
    return datetime.now().strftime("%Y%m")


def load_manifest():
    p = DATA / "manifest.json"
    try:
        return list(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return []


def months_ago(ym, now=None):
    now = now or datetime.now()
    y, m = int(ym[:4]), int(ym[4:6])
    return (now.year - y) * 12 + (now.month - m)


def prune_old_versions(month):
    """같은 달 구버전 엑셀 제거 — 최신 1개만 남겨 중복 가공 방지."""
    d = DATA / month[:4]
    if not d.exists():
        return
    files = sorted(d.glob(f"실거래_{month}_*.xlsx"), key=lambda f: f.stat().st_mtime)
    for f in files[:-1]:
        print(f"  구버전 제거: {f.name}", flush=True)
        f.unlink()


def commit_push(msg):
    print("\n===== 커밋 / 푸시 =====", flush=True)
    subprocess.run(["git", "add", "-A", "data/"], cwd=ROOT)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        print("변경 없음 — 커밋 생략", flush=True)
        return
    subprocess.run(["git", "commit", "-m", msg], cwd=ROOT)
    rc = subprocess.run(["git", "push", "origin", "master"], cwd=ROOT).returncode
    print("[완료] 배포" + ("" if rc == 0 else " (푸시 실패 — 수동 확인 필요)"), flush=True)


def do_current(month):
    print(f"[이번 달 갱신] {month}", flush=True)
    if run(PY + ["scripts/land.py", "-n"], "① 실거래 다운로드") != 0:
        print("[!] 다운로드 실패 — 중단", flush=True)
        return
    prune_old_versions(month)
    if run(PY + ["scripts/data_manager.py", "-m", month], "② 데이터 가공") != 0:
        print("[!] 가공 실패 — 커밋 생략", flush=True)
        return
    commit_push(f"Data: {month} 월간 실거래 갱신 (자동)")


def do_backfill():
    cur = current_month()
    have = set(load_manifest())
    latest = max(have) if have else cur
    # latest 이후 ~ 현재월 중 manifest에 없는 달
    span = months_ago(latest)               # latest가 몇 달 전인지
    candidates = []
    for k in range(span, -1, -1):           # latest 달 → 현재월
        y = datetime.now().year
        m = datetime.now().month - k
        while m <= 0:
            m += 12
            y -= 1
        candidates.append(f"{y}{m:02d}")
    missing = [m for m in candidates if m not in have]
    if not missing:
        print("[밀린 달 채우기] 빠진 달 없음 — 이번 달만 갱신", flush=True)
        return do_current(cur)
    print(f"[밀린 달 채우기] 대상 {len(missing)}개: {', '.join(missing)}", flush=True)
    x = months_ago(min(missing))            # 가장 오래된 빠진 달
    y = x + 1                               # 그달 ~ 현재월
    if run(PY + ["scripts/land.py", "-n", str(x), str(y)], "① 밀린 달 다운로드") != 0:
        print("[!] 다운로드 실패 — 중단", flush=True)
        return
    for m in missing:
        prune_old_versions(m)
    # 인자 없는 data_manager = manifest에 없는 달만 가공 (=빠진 달 정확히)
    if run(PY + ["scripts/data_manager.py"], "② 빠진 달 가공") != 0:
        print("[!] 가공 실패 — 커밋 생략", flush=True)
        return
    commit_push(f"Data: 밀린 달 채우기 ({missing[0]}~{missing[-1]}, {len(missing)}개월)")


def do_rebuild():
    print("[전체 재생성] 재다운로드 없이 기존 엑셀로 전 기간 재가공", flush=True)
    if run(PY + ["scripts/data_manager.py", "-r"], "① 전체 재생성") != 0:
        print("[!] 재생성 실패 — 커밋 생략", flush=True)
        return
    commit_push("Data: 전체 재생성 (구조 변경 반영)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="빠진 달을 현재월까지 채움")
    ap.add_argument("--rebuild", action="store_true", help="기존 엑셀로 전체 재가공")
    ap.add_argument("month", nargs="?", help="특정 월(YYYYMM) — 기본은 현재월")
    a = ap.parse_args()
    if a.rebuild:
        do_rebuild()
    elif a.backfill:
        do_backfill()
    else:
        do_current(a.month or current_month())


if __name__ == "__main__":
    main()

# panel.py — 로컬 관리 서버 (정적 앱 + 원클릭 실행 API)
#
# 기존 실행.bat의 `python -m http.server 8080`을 대체한다.
#  - data/ 정적 파일 서빙(index.html, app.js, JSON…) → 앱은 그대로 동작
#  - GET  /panel            대시보드(panel.html)
#  - GET  /api/status       데이터 파일에서 실시간 진행 수치 집계
#  - GET  /api/log          현재/직전 작업 로그 tail
#  - POST /api/run/monthly  update_monthly.py 실행 (월간 갱신 원클릭)
#  - POST /api/run/ledger   bldg_ledger.py 실행 (건축물대장 이어받기)
#
# 실행: python panel.py   (실행.bat이 자동으로 띄움)

import json
import socket
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
# 포트: 인자 > 기본 8080 (카카오 지도 키가 localhost:8080에 등록돼 있어 기본 고정)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8080
JOB_LOG = ROOT / "panel_job.log"

_job = {"running": False, "name": None, "started": None, "rc": None}
_lock = threading.Lock()


def _run_job(name, cmd):
    with _lock:
        if _job["running"]:
            return False
        _job.update(running=True, name=name, started=time.strftime("%H:%M:%S"), rc=None)

    def worker():
        rc = -1
        try:
            with open(JOB_LOG, "w", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {name} 시작\n")
                f.write("> " + " ".join(cmd) + "\n\n")
                f.flush()
                p = subprocess.Popen(cmd, cwd=ROOT, stdout=f,
                                     stderr=subprocess.STDOUT, bufsize=1)
                p.wait()
                rc = p.returncode
                f.write(f"\n[{time.strftime('%H:%M:%S')}] 종료 (exit {rc})\n")
        except Exception as e:  # noqa
            try:
                JOB_LOG.write_text(f"[오류] {e}\n", encoding="utf-8")
            except Exception:
                pass
        with _lock:
            _job.update(running=False, rc=rc)

    threading.Thread(target=worker, daemon=True).start()
    return True


def _load(rel):
    try:
        return json.loads((DATA / rel).read_text(encoding="utf-8"))
    except Exception:
        return None


def _status():
    area = _load("ledger_cache/area.json") or {}
    title = _load("ledger_cache/title.json") or {}
    bjd = _load("hspms_cache/bjd_map.json") or {}
    ratio = _load("bldg_ratio.json") or {}
    mc = _load("match_cache.json") or {}
    hdir = DATA / "hierarchy"
    months = sorted([d.name for d in hdir.iterdir() if d.is_dir()]) if hdir.exists() else []

    def cnt(rel):
        d = _load(rel)
        return len(d) if isinstance(d, (list, dict)) else 0

    return {
        "months": len(months),
        "month_first": months[0] if months else None,
        "month_last": months[-1] if months else None,
        "supply": cnt("supply_area.json"),
        "apt_info": cnt("apt_info.json"),
        "no_deal": cnt("no_deal_apts.json"),
        "gsi": cnt("global_search_index.json"),
        "redev": cnt("redev_polygons.json"),
        "ratio_total": len(ratio),
        "ratio_val": sum(1 for v in ratio.values() if v.get("vl") or v.get("bc")),
        "match_total": len(mc),
        "match_hit": sum(1 for v in mc.values() if v),
        "ledger_area": len(area),
        "ledger_title": len(title),
        "ledger_total": len(bjd),
        "job": _job,
    }


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # 콘솔 조용히
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/status":
            return self._json(_status())
        if p == "/api/log":
            tail = ""
            if JOB_LOG.exists():
                tail = JOB_LOG.read_text(encoding="utf-8", errors="replace")[-8000:]
            return self._json({"job": _job, "log": tail})
        if p in ("/panel", "/panel/"):
            self.path = "/panel.html"
        return super().do_GET()

    def do_POST(self):
        p = self.path.split("?")[0]
        if p == "/api/run/monthly":
            ok = _run_job("월간 실거래 갱신",
                          [sys.executable, "-X", "utf8", "update_monthly.py"])
            return self._json({"ok": ok, "job": _job})
        if p == "/api/run/backfill":
            ok = _run_job("밀린 달 채우기",
                          [sys.executable, "-X", "utf8", "update_monthly.py", "--backfill"])
            return self._json({"ok": ok, "job": _job})
        if p == "/api/run/rebuild":
            ok = _run_job("전체 재생성",
                          [sys.executable, "-X", "utf8", "update_monthly.py", "--rebuild"])
            return self._json({"ok": ok, "job": _job})
        if p == "/api/run/ledger":
            ok = _run_job("건축물대장 수집",
                          [sys.executable, "-X", "utf8", "bldg_ledger.py"])
            return self._json({"ok": ok, "job": _job})
        return self._json({"error": "unknown"}, 404)


class DualStackServer(ThreadingHTTPServer):
    """IPv4·IPv6 동시 수신 — localhost가 ::1(IPv6)로 풀려도 응답한다.
    (옛 http.server가 IPv6를 잡고 있으면 /panel이 404 나던 문제 방지)"""
    address_family = socket.AF_INET6
    allow_reuse_address = True

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        return super().server_bind()


def main():
    handler = partial(Handler, directory=str(DATA))
    try:
        httpd = DualStackServer(("", PORT), handler)
    except OSError as e:
        print(f"[panel] 포트 {PORT} 사용 중 — 기존 서버를 먼저 종료하세요. ({e})")
        sys.exit(1)
    print(f"[panel] 관리 서버 실행 → http://localhost:{PORT}/")
    print(f"[panel] 대시보드     → http://localhost:{PORT}/panel")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[panel] 종료")


if __name__ == "__main__":
    main()

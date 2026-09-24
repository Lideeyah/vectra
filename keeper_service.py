"""The keeper as a long running process, for a host that keeps things alive.

Why this exists
---------------
The keeper used to live entirely in .github/workflows/keeper.yml: a `while`
loop in YAML, alive for 170 minutes, restarted by `cron: */15`. GitHub's cron
is best effort and was observed firing roughly every four hours against a five
minute schedule, so in practice the run was restarted by hand. All twenty three
legs on chain came from manual `workflow_dispatch` starts and none from cron.

The pacing therefore moves out of the scheduler and into a process that a host
can be responsible for restarting.

Shape
-----
The cycle loop runs in a background thread and a small status server binds
`$PORT`. Deployed as a WORKER the port is simply unused; deployed as a WEB
service it satisfies the platform health check, and the same URL doubles as a
keep-awake target and as a heartbeat you can read.

That second job matters. A keep awake pinger is itself a thing that can stop,
which is the same failure class as the cron this replaces. The difference is
that `/` reports the age of the last cycle, so a stopped keeper is visible
rather than discovered later.

Restarts are safe. A cycle holds no state between runs: positions, targets and
spentUsdc are read from chain every time, so a restart costs one cycle and
never correctness.

Run
---
    VECTRA_AGENT_KEY=... python3 keeper_service.py

Environment: VECTRA_CYCLE_MIN (default 5), VECTRA_COMMIT_EVERY (default 3),
PORT (default 8000), plus everything agent.py already reads.
"""

import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).parent
CYCLE_MIN = float(os.environ.get("VECTRA_CYCLE_MIN", "5"))
COMMIT_EVERY = int(os.environ.get("VECTRA_COMMIT_EVERY", "3"))
PORT = int(os.environ.get("PORT", "8000"))

# Render's free tier stops a web service after about 15 minutes with no
# inbound request, and a stopped service is a stopped keeper. RENDER_EXTERNAL_URL
# is set by the platform, so the service can keep itself awake without a second
# account to maintain.
SELF_URL = os.environ.get("VECTRA_SELF_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")
PING_MIN = float(os.environ.get("VECTRA_PING_MIN", "10"))

STARTED = time.time()
STATE = {
    "cycles": 0,
    "last_cycle_utc": None,
    "last_exit_code": None,
    "last_error": None,
    "commits_attempted": 0,
    "commits_failed": 0,
    "can_push": None,
    "self_ping": None,
}
LOCK = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"{now()}  {msg}", flush=True)


def can_push() -> tuple[bool, str]:
    """Whether committed cycle logs can actually reach the repository.

    Reported rather than assumed, because the failure is silent and has already
    cost this project a series once. Several build platforms hand the service a
    directory that is not a git checkout at all, in which case the agent still
    trades correctly and simply publishes nothing.
    """
    if not (ROOT / ".git").exists():
        return False, "not a git checkout on this host"
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("VECTRA_GIT_TOKEN")
    if not token:
        return False, "no GITHUB_TOKEN or VECTRA_GIT_TOKEN in the environment"
    return True, "token present"


def one_cycle() -> int:
    """Run agent.py as a child process.

    A subprocess rather than an import, so that a crash inside a cycle cannot
    take the loop down with it, and so this runs exactly what the workflow ran.
    The environment is inherited, which is how VECTRA_AGENT_KEY reaches it: the
    key is never an argument and never printed here.
    """
    r = subprocess.run([sys.executable, "agent.py"], cwd=ROOT)
    return r.returncode


def commit() -> bool:
    ok, why = can_push()
    if not ok:
        log(f"skipping commit: {why}")
        return False
    r = subprocess.run(
        ["bash", "scripts/commit_data.sh", f"record: {now()}", "data"],
        cwd=ROOT,
    )
    return r.returncode == 0


def loop() -> None:
    ok, why = can_push()
    with LOCK:
        STATE["can_push"] = ok
    log(f"publishing: {why}")
    log(f"cycle every {CYCLE_MIN} min, committing every {COMMIT_EVERY} cycles")

    while True:
        start = time.time()
        try:
            code = one_cycle()
            err = None
        except Exception as e:                      # never let the loop die
            code, err = -1, repr(e)[:300]
            log(f"cycle raised: {err}")

        with LOCK:
            STATE["cycles"] += 1
            STATE["last_cycle_utc"] = now()
            STATE["last_exit_code"] = code
            STATE["last_error"] = err
            n = STATE["cycles"]

        if n % COMMIT_EVERY == 0:
            with LOCK:
                STATE["commits_attempted"] += 1
            if not commit():
                with LOCK:
                    STATE["commits_failed"] += 1

        # Pace from the START of the cycle, so a slow cycle does not push the
        # next one later and later until the interval has quietly doubled.
        sleep = max(5.0, CYCLE_MIN * 60 - (time.time() - start))
        time.sleep(sleep)


def keep_awake() -> None:
    """Hit our own public URL so the platform sees inbound traffic.

    A request to the external URL goes out and back through the platform's
    router, which is what the idle timer actually watches; a loopback request
    to 127.0.0.1 would not count.

    This keeps a running service running. It CANNOT wake one that has already
    stopped, because a stopped service cannot make requests. An external
    monitor is still the thing that recovers from a stop, and it is worth
    having one pointed at / for that reason alone.
    """
    if not SELF_URL:
        log("no RENDER_EXTERNAL_URL or VECTRA_SELF_URL; self-ping disabled")
        with LOCK:
            STATE["self_ping"] = "disabled: no url"
        return

    log(f"self-ping every {PING_MIN} min to {SELF_URL}")
    while True:
        time.sleep(PING_MIN * 60)
        try:
            with urllib.request.urlopen(SELF_URL, timeout=30) as r:
                ok = f"{r.status} at {now()}"
        except Exception as e:
            # Never fatal. A failed ping means the idle timer keeps counting,
            # which is a problem to see rather than to crash over.
            ok = f"failed at {now()}: {type(e).__name__}"
            log(f"self-ping {ok}")
        with LOCK:
            STATE["self_ping"] = ok


def status() -> dict:
    with LOCK:
        s = dict(STATE)
    age = None
    if s["last_cycle_utc"]:
        age = round(
            (datetime.now(timezone.utc)
             - datetime.fromisoformat(s["last_cycle_utc"])).total_seconds())

    # The agent's own published decision, not a second opinion computed here.
    leg = None
    try:
        d = json.loads((ROOT / "data/agent/latest.json").read_text())
        leg = {"cycle_utc": d.get("ts"),
               "leg": d.get("leg"),
               "no_action": d.get("noActionReason")}
    except Exception:
        pass

    return {
        "ok": s["last_exit_code"] in (0, None),
        "uptime_s": round(time.time() - STARTED),
        "cycle_minutes": CYCLE_MIN,
        "seconds_since_last_cycle": age,
        **s,
        "latest_published_cycle": leg,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(status(), indent=1).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass        # keep-awake pings would otherwise bury the cycle output


if __name__ == "__main__":
    # Fail at startup rather than deciding for hours without sending. The
    # workflow this replaces made the same check for the same reason: a keeper
    # that cannot sign is not a keeper, and on a host with a restart policy a
    # hard exit is visible as a crash loop instead of silence.
    if not os.environ.get("VECTRA_AGENT_KEY"):
        sys.exit("VECTRA_AGENT_KEY is not set")

    threading.Thread(target=loop, daemon=True).start()
    threading.Thread(target=keep_awake, daemon=True).start()
    log(f"status on :{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

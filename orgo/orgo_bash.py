#!/usr/bin/env python3
# orgo_bash.py — pure-Python orgo /bash client. urllib only (no deps).
# Usage: ORGO_API_KEY=… CID=… python3 orgo_bash.py "command string"
# (Documented in ORGO-CLIENT-TEMPLATE.md "Operator helper"; orgo throws
#  503/502/conn-refused bursts lasting 30-60s — retry 6x, 5→30s backoff.)
import json, os, sys, time, urllib.request, urllib.error

API_KEY = os.environ["ORGO_API_KEY"]
CID     = os.environ["CID"]
URL     = f"https://www.orgo.ai/api/computers/{CID}/bash"

def run(cmd, retries=6):
    body = json.dumps({"command": cmd}).encode()
    backoff = 5
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                URL, data=body, method="POST",
                headers={"Authorization": f"Bearer {API_KEY}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read().decode()
        except (urllib.error.HTTPError, urllib.error.URLError, ConnectionError, TimeoutError) as e:
            # orgo throws 503/502/connection-refused bursts that last 30-60s.
            last = e
            code = getattr(e, "code", "conn")
            sys.stderr.write(f"[orgo_bash] attempt {attempt}/{retries} failed ({code}); "
                             f"retrying in {backoff}s\n")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)   # 5,10,20,30,30…
    raise SystemExit(f"[orgo_bash] all {retries} attempts failed: {last}")

if __name__ == "__main__":
    print(run(sys.argv[1]))

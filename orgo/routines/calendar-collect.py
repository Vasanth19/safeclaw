#!/usr/bin/env python3
# Deterministic Google Calendar collector, Composio transport.
# Composio owns OAuth + refresh; we just call the events.list tool and write
# gbrain daily files at /opt/brain/repo/daily/calendar/{YYYY}/{YYYY-MM-DD}.md.
# Idempotent: same range => same files. No LLM in this step.
#   usage: calendar-collect.py [DAYS_BACK]   (default 365)
import json, os, sys, re, datetime, urllib.request
from collections import defaultdict

COMPOSIO = "https://backend.composio.dev/api/v3"
ROOT = "/opt/brain/repo/daily/calendar"

def composio_key():
    for line in open("/root/.hermes/.env"):
        if line.startswith("COMPOSIO_API_KEY="):
            return line.strip().split("=", 1)[1]
    raise SystemExit("no COMPOSIO_API_KEY")

KEY = composio_key()

def get(path):
    req = urllib.request.Request(COMPOSIO + path, headers={"x-api-key": KEY})
    return json.load(urllib.request.urlopen(req, timeout=30))

def execute(args):
    body = json.dumps({"user_id": UE, "connected_account_id": CA, "arguments": args}).encode()
    req = urllib.request.Request(COMPOSIO + "/tools/execute/GOOGLECALENDAR_EVENTS_LIST",
                                 data=body, method="POST",
                                 headers={"x-api-key": KEY, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=45))

def find_items(o):
    if isinstance(o, dict):
        if isinstance(o.get("items"), list):
            return o["items"]
        for v in o.values():
            r = find_items(v)
            if r is not None:
                return r
    return None

def find_npt(o):
    if isinstance(o, dict):
        if o.get("nextPageToken"):
            return o["nextPageToken"]
        for v in o.values():
            r = find_npt(v)
            if r:
                return r
    return None

# resolve the active calendar connection
accs = get("/connected_accounts?limit=100&statuses=ACTIVE")["items"]
acc = next((a for a in accs if a["toolkit"]["slug"] == "googlecalendar"), None)
if not acc:
    raise SystemExit("no ACTIVE googlecalendar connection")
CA, UE = acc["id"], acc["user_id"]

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 365
end = datetime.datetime.utcnow()
start = end - datetime.timedelta(days=DAYS)
timeMin = start.strftime("%Y-%m-%dT00:00:00Z")
timeMax = end.strftime("%Y-%m-%dT23:59:59Z")

events, token, pages = [], None, 0
while True:
    args = {"calendarId": "primary", "timeMin": timeMin, "timeMax": timeMax,
            "singleEvents": True, "orderBy": "startTime", "maxResults": 250}
    if token:
        args["pageToken"] = token
    r = execute(args)
    if not r.get("successful", True):
        print("API error:", str(r.get("error"))[:200]); break
    events += find_items(r) or []
    pages += 1
    token = find_npt(r)
    if not token or pages > 60:
        break

def attendee_names(e):
    out = []
    for a in e.get("attendees", []) or []:
        if a.get("self"):
            continue
        n = a.get("displayName") or (a.get("email", "").split("@")[0] if a.get("email") else "")
        if n:
            out.append(n)
    return out

days = defaultdict(list)
for e in events:
    if e.get("status") == "cancelled":
        continue
    st = e.get("start", {}) or {}
    dt = st.get("dateTime") or st.get("date")
    if dt:
        days[dt[:10]].append(e)

written = 0
for day, evs in sorted(days.items()):
    d = os.path.join(ROOT, day[:4])
    os.makedirs(d, exist_ok=True)
    out = ["---", f"title: Calendar {day}", f"date: {day}", "source: google-calendar",
           "---", "", f"# Calendar — {day}", ""]
    for e in sorted(evs, key=lambda x: (x.get("start", {}).get("dateTime") or x.get("start", {}).get("date") or "")):
        st = e.get("start", {}) or {}
        t = (st.get("dateTime") or "")[11:16] or "all day"
        out.append(f"## {t} {e.get('summary','(no title)')}")
        att = attendee_names(e)
        if att:
            out.append(f"- Attendees: {', '.join(att)}")
        if e.get("location"):
            out.append(f"- Location: {e['location']}")
        if e.get("description"):
            desc = re.sub(r"\s+", " ", e["description"]).strip()[:300]
            if desc:
                out.append(f"- Notes: {desc}")
        out.append("")
    open(os.path.join(d, f"{day}.md"), "w").write("\n".join(out))
    written += 1

print(f"COLLECT DONE: {len(events)} events over {DAYS}d, {written} day-files, {pages} api pages")

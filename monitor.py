import os, re, json, time, urllib.parse, requests
from pathlib import Path

# ---------- Settings ----------
URLS    = [u.strip() for u in os.getenv("URLS", "").split(",") if u.strip()]
TIMEOUT = int(os.getenv("TIMEOUT", "10"))
EXPECT  = os.getenv("EXPECT", "").strip()

CALLMEBOT_PHONE  = os.getenv("CALLMEBOT_PHONE", "").strip()
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "").strip()

STATE_FILE = os.getenv("STATE_FILE", ".uptime_state/state.json")
Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)

# Tuning knobs
FAILURE_THRESHOLD = max(1, int(os.getenv("FAILURE_THRESHOLD", "2")))
REMIND_MIN        = int(os.getenv("REMIND_MIN", "10"))  # 0 = no reminder while down

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ---------- HTTP check ----------
def check_url(u: str):
    """Return (ok, message). ok=False if HTTP>=400, timeout, or EXPECT missing."""
    try:
        r = requests.get(
            u, timeout=TIMEOUT, allow_redirects=True,
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml"}
        )
        if r.status_code >= 400:
            return False, f"{u} returned {r.status_code}"
        if EXPECT and not re.search(EXPECT, r.text, re.I | re.M):
            return False, f"{u} missing expected content"
        return True, f"{u} OK ({r.status_code})"
    except Exception as e:
        return False, f"{u} error: {e}"

def notify_callmebot(text: str):
    if not (CALLMEBOT_PHONE and CALLMEBOT_APIKEY):
        return
    try:
        base = "https://api.callmebot.com/whatsapp.php"
        params = {"phone": CALLMEBOT_PHONE, "text": text, "apikey": CALLMEBOT_APIKEY}
        url = f"{base}?{urllib.parse.urlencode(params)}"
        r = requests.get(url, timeout=15)
        if r.status_code >= 300:
            print(f"CallMeBot failed: {r.status_code}, {r.text[:200]}", flush=True)
    except Exception as e:
        print(f"CallMeBot error: {e}", flush=True)

# ---------- State I/O ----------
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def empty_entry():
    return {
        "status": "up",               # "up" | "down"
        "fail": 0,                    # consecutive failures
        "ok": 0,                      # consecutive successes
        "last_change": 0,             # epoch when status last changed
        "last_down_alert": 0          # epoch when last DOWN alert/reminder sent
    }

# ---------- Main ----------
def main():
    if not URLS:
        print("No URLS set. Edit URLS in workflow env.", flush=True)
        raise SystemExit(2)

    prev = load_state()  # {url: entry}
    curr = {}
    now  = int(time.time())

    down_alerts = []
    recover_alerts = []

    for u in URLS:
        entry = prev.get(u, empty_entry())
        ok, msg = check_url(u)
        print(msg, flush=True)

        if ok:
            entry["ok"] += 1
            entry["fail"] = 0

            # Recovery only if previously DOWN
            if entry["status"] == "down":
                entry["status"] = "up"
                entry["last_change"] = now
                recover_alerts.append(f"{u} recovered ✅")
        else:
            entry["fail"] += 1
            entry["ok"] = 0

            if entry["status"] != "down":
                # Transition to DOWN after N consecutive failures
                if entry["fail"] >= FAILURE_THRESHOLD:
                    entry["status"] = "down"
                    entry["last_change"] = now
                    entry["last_down_alert"] = now
                    down_alerts.append(msg)
            else:
                # Already DOWN: send reminder if enabled and interval passed
                if REMIND_MIN > 0 and now - entry.get("last_down_alert", 0) >= REMIND_MIN * 60:
                    entry["last_down_alert"] = now
                    down_alerts.append(msg + " (still down)")

        curr[u] = entry

    # Send notifications
    if down_alerts:
        notify_callmebot("⚠️ Uptime alert:\n" + "\n".join(down_alerts))
    if recover_alerts:
        notify_callmebot("✅ Recovery:\n" + "\n".join(recover_alerts))

    # Persist state BEFORE exiting
    save_state(curr)

    # Keep job red if any URL is currently DOWN
    any_down = any(e["status"] == "down" for e in curr.values())
    if any_down:
        raise SystemExit(1)

    print("All checks passed ✅", flush=True)

if __name__ == "__main__":
    main()

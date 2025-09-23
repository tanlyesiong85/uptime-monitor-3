import os, re, json, urllib.parse, requests
from pathlib import Path

# -------- Settings from env --------
URLS    = [u.strip() for u in os.getenv("URLS","").split(",") if u.strip()]
TIMEOUT = int(os.getenv("TIMEOUT","10"))
EXPECT  = os.getenv("EXPECT","").strip()

CALLMEBOT_PHONE = os.getenv("CALLMEBOT_PHONE","").strip()
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY","").strip()

# State file path (persisted via Actions cache)
STATE_FILE = os.getenv("STATE_FILE", ".uptime_state/state.json")
Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

def check_url(u: str):
    """Return (ok, message). ok=False if HTTP>=400, timeout, or EXPECT missing."""
    try:
        r = requests.get(
            u, timeout=TIMEOUT, allow_redirects=True,
            headers={"User-Agent": BROWSER_UA, "Accept":"text/html,application/xhtml+xml"}
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

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}  # first run or unreadable

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def main():
    if not URLS:
        print("No URLS set. Edit URLS in workflow env.", flush=True)
        raise SystemExit(2)

    prev = load_state()                 # {url: "up"|"down"}
    curr = {}

    downs = []
    ups_recovered = []

    for u in URLS:
        ok, msg = check_url(u)
        print(msg, flush=True)
        curr[u] = "up" if ok else "down"

        was = prev.get(u)  # None on first run
        if not ok:
            downs.append(msg)  # down now (always notify)
        elif was == "down":    # just recovered
            ups_recovered.append(f"{u} recovered ✅")

    # Send notifications
    if downs:
        notify_callmebot("⚠️ Uptime alert:\n" + "\n".join(downs))
    if ups_recovered:
        notify_callmebot("✅ Recovery:\n" + "\n".join(ups_recovered))

    # Persist new state for the next run
    save_state(curr)

    # Make the job fail only if something is down (keeps your red signal)
    if downs:
        raise SystemExit(1)

    print("All checks passed ✅", flush=True)

if __name__ == "__main__":
    main()

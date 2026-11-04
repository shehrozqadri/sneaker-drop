"""
Sneaker Drop - LaunchDarkly SE exercise (Python / Flask)

Demonstrates:
  Part 1  Release & Remediate : flag `one-click-checkout`, instant on/off via SDK
                                change listener + Server-Sent Events, flag trigger kill switch
  Part 2  Target              : flag `new-landing-hero`, individual + rule-based targeting
  Extra   Experimentation     : custom event `hero-cta-click` sent with client.track()

Run:  cp .env.example .env  (add LD_SDK_KEY)  ->  python app.py  ->  http://localhost:5000
"""
import atexit
import json
import os
import queue
import threading

import ldclient
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from ldclient import Context
from ldclient.config import Config

load_dotenv()  # reads .env if present (see .env.example); real env vars still win

# ---------------------------------------------------------------------------
# >>> REPLACE ME: server-side SDK key (LaunchDarkly > Project settings >
# >>> Environments > SDK keys). Put it in .env as LD_SDK_KEY=sdk-xxxx, or
# >>> export LD_SDK_KEY in your shell. The fallback below is a placeholder.
# ---------------------------------------------------------------------------
SDK_KEY = os.environ.get("LD_SDK_KEY", "sdk-REPLACE-ME")

# Flags to create in your LaunchDarkly project (Boolean, same environment as the SDK key):
FLAG_CHECKOUT = "one-click-checkout"   # Part 1 - release / rollback / trigger
FLAG_HERO = "new-landing-hero"         # Part 2 - targeting (also the experiment flag)
FLAGS = [FLAG_CHECKOUT, FLAG_HERO]

# Demo shoppers. Their attributes are what the targeting rules match on.
PERSONAS = {
    "qa-sam":    {"name": "Sam (QA team)",        "tier": "Standard", "country": "IN", "device_type": "desktop", "beta_tester": True},
    "priya":     {"name": "Priya (Premium)",      "tier": "Premium",  "country": "IN", "device_type": "mobile",  "beta_tester": False},
    "jordan":    {"name": "Jordan (Beta tester)", "tier": "Standard", "country": "GB", "device_type": "mobile",  "beta_tester": True},
    "alex":      {"name": "Alex (Standard, US)",  "tier": "Standard", "country": "US", "device_type": "desktop", "beta_tester": False},
    "guest-4821": {"name": "Guest (anonymous)",   "tier": "Free",     "country": "DE", "device_type": "mobile",  "beta_tester": False},
}

app = Flask(__name__)

ldclient.set_config(Config(SDK_KEY))
ld = ldclient.get()  # opens the streaming connection
atexit.register(ld.close)  # flush pending analytics events on shutdown
if not ld.is_initialized():
    print("WARNING: LaunchDarkly client not initialized - check LD_SDK_KEY. Flags will use defaults (False).")


def build_context(user_key: str) -> Context:
    """Turn a persona into an LD context (kind=user) with custom attributes."""
    p = PERSONAS.get(user_key, PERSONAS["guest-4821"])
    return (Context.builder(user_key).kind("user").name(p["name"])
            .set("tier", p["tier"]).set("country", p["country"])
            .set("device_type", p["device_type"]).set("beta_tester", p["beta_tester"]).build())


# ---------------------------------------------------------------------------
# Instant updates: SDK change listener -> fan out to every open browser (SSE)
# ---------------------------------------------------------------------------
subscribers: list[queue.Queue] = []
sub_lock = threading.Lock()


def on_flag_change(change):
    """Called by the SDK the moment LaunchDarkly streams a flag change."""
    print(f"[LD] flag changed: {change.key}")
    msg = json.dumps({"flag": change.key})
    with sub_lock:
        for q in subscribers:
            q.put(msg)


ld.flag_tracker.add_listener(on_flag_change)


@app.route("/")
def index():
    return render_template("index.html", personas=PERSONAS)


@app.route("/health")
def health():
    """Troubleshooting: is the SDK connected? (False usually means a wrong SDK key.)"""
    return jsonify(ld_initialized=ld.is_initialized(), flags=FLAGS)


@app.route("/api/flags")
def flags():
    """Evaluate flags for the selected shopper. Default (False) = existing experience."""
    ctx = build_context(request.args.get("user", "guest-4821"))
    return jsonify({k: ld.variation(k, ctx, False) for k in FLAGS})


@app.route("/api/track", methods=["POST"])
def track():
    """Send a custom event; use it as the metric for the experiment (extra credit)."""
    ctx = build_context(request.json.get("user", "guest-4821"))
    ld.track("hero-cta-click", ctx)
    return jsonify(ok=True)


@app.route("/stream")
def stream():
    q: queue.Queue = queue.Queue()
    with sub_lock:
        subscribers.append(q)

    def gen():
        try:
            while True:
                try:
                    yield f"data: {q.get(timeout=15)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with sub_lock:
                subscribers.remove(q)

    return Response(gen(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    # threaded=True is required: each open browser holds a long-lived /stream connection.
    # macOS AirPlay Receiver often occupies 5000 - set PORT=5001 in .env if so.
    app.run(port=int(os.environ.get("PORT", 5000)), threaded=True)

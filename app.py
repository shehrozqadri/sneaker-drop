"""
Sneaker Drop - a LaunchDarkly feature-flag demo (Python 3.9+ / Flask).

What this file does, top to bottom:

  1. Configuration        read the SDK key from .env, name the two flags
  2. Demo shoppers        five fake users whose attributes drive targeting
  3. LaunchDarkly client  open the streaming connection, keep it open
  4. Contexts             turn a shopper into a LaunchDarkly "context"
  5. Live updates         SDK change listener -> Server-Sent Events -> browser
  6. HTTP routes          page, flag evaluation, event tracking, health check
  7. Entrypoint           start Flask

Exercise mapping:
  Part 1  Release & Remediate   flag `one-click-checkout`  (sections 5 and 6)
  Part 2  Target                flag `new-landing-hero`    (sections 2, 4 and 6)
  Extra   Experimentation       event `hero-cta-click`     (section 6, /api/track)

Run:
  cp .env.example .env     # paste your LaunchDarkly server-side SDK key
  python app.py            # http://localhost:5000
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


# ===========================================================================
# 1. CONFIGURATION
# ===========================================================================

# Load variables from a local .env file if one exists. Real environment
# variables (e.g. `export LD_SDK_KEY=...`) take precedence over the file.
load_dotenv()

# ---------------------------------------------------------------------------
# >>> REPLACE ME <<<
# Your LaunchDarkly *server-side* SDK key. Find it in the LaunchDarkly UI:
#   Project settings -> Environments -> (your environment) -> SDK keys
# It starts with "sdk-". Do NOT use the client-side ID or the mobile key.
#
# Preferred: put it in .env as   LD_SDK_KEY=sdk-xxxxxxxx
# The fallback string below is a placeholder and will not connect.
# ---------------------------------------------------------------------------
SDK_KEY = os.environ.get("LD_SDK_KEY", "sdk-REPLACE-ME")

# The two Boolean flags this app reads. Create them in LaunchDarkly with
# exactly these keys, in the same environment the SDK key belongs to.
FLAG_CHECKOUT = "one-click-checkout"   # Part 1: shows/hides the "Buy now" button
FLAG_HERO = "new-landing-hero"         # Part 2: picks old vs new landing hero
FLAGS = [FLAG_CHECKOUT, FLAG_HERO]

# The custom event sent when a shopper clicks the new hero's call-to-action.
# Used as the metric for the experiment (extra credit).
EVENT_HERO_CTA = "hero-cta-click"

# Everything the reviewer needs to set up in LaunchDarkly (same environment
# as the SDK key). Step-by-step instructions are in README section 3.
#
#   Flag     one-click-checkout   Boolean, targeting Off, default false
#   Trigger  on one-click-checkout: generic trigger, action "turn flag off"
#   Flag     new-landing-hero     Boolean, targeting On:
#              individual target  user key "qa-sam"            -> true
#              rule               tier is one of "Premium"     -> true
#              rule               beta_tester is one of true   -> true
#              default rule                                    -> false
#   Metric   "Hero CTA click"     custom event "hero-cta-click", occurrence
#   Experiment (optional)         new-landing-hero, default rule, 50/50,
#                                 metric "Hero CTA click"


# ===========================================================================
# 2. DEMO SHOPPERS
# ===========================================================================

# Five pretend users. The browser shows them in a dropdown; whichever one is
# selected becomes the LaunchDarkly context for every flag evaluation.
#
# The attributes are what you write targeting rules against in LaunchDarkly.
# Expected result once the README's targeting is configured:
#
#   qa-sam      -> new hero   (individual target on the key)
#   priya       -> new hero   (rule: tier is one of Premium)
#   jordan      -> new hero   (rule: beta_tester is true)
#   alex        -> old hero   (no rule matches -> default rule)
#   guest-4821  -> old hero   (no rule matches -> default rule)
PERSONAS = {
    "qa-sam":     {"name": "Sam (QA team)",        "tier": "Standard", "country": "IN", "device_type": "desktop", "beta_tester": True},
    "priya":      {"name": "Priya (Premium)",      "tier": "Premium",  "country": "IN", "device_type": "mobile",  "beta_tester": False},
    "jordan":     {"name": "Jordan (Beta tester)", "tier": "Standard", "country": "GB", "device_type": "mobile",  "beta_tester": True},
    "alex":       {"name": "Alex (Standard, US)",  "tier": "Standard", "country": "US", "device_type": "desktop", "beta_tester": False},
    "guest-4821": {"name": "Guest (anonymous)",    "tier": "Free",     "country": "DE", "device_type": "mobile",  "beta_tester": False},
}
DEFAULT_PERSONA = "guest-4821"


# ===========================================================================
# 3. LAUNCHDARKLY CLIENT
# ===========================================================================

app = Flask(__name__)

# One client per process. ldclient.get() opens a long-lived streaming
# connection to LaunchDarkly, downloads all flag rules, and keeps them in
# memory. From then on every ld.variation() call is a local lookup - no
# network round-trip - and rule changes arrive over the stream in ~1s.
ldclient.set_config(Config(SDK_KEY))
ld = ldclient.get()

# Flush any queued analytics events (flag evaluations, custom events) when
# the process exits, so nothing is lost on Ctrl-C.
atexit.register(ld.close)

# If the key is wrong or missing, the SDK still starts but every evaluation
# returns the fallback value you pass in (False here). The UI shows a red
# banner in that case; /health reports the same thing.
if not ld.is_initialized():
    print("WARNING: LaunchDarkly client not initialized. Check LD_SDK_KEY in .env. "
          "All flags will evaluate to their fallback (False).")


# ===========================================================================
# 4. CONTEXTS
# ===========================================================================

def build_context(user_key: str) -> Context:
    """
    Convert a persona into a LaunchDarkly context.

    A context is "who is asking". It has a kind ("user" here), a unique key,
    and any attributes you want to target on. LaunchDarkly evaluates the
    flag's rules against these attributes server-side and returns one value.
    Unknown keys fall back to the anonymous guest.
    """
    p = PERSONAS.get(user_key, PERSONAS[DEFAULT_PERSONA])
    return (
        Context.builder(user_key)
        .kind("user")
        .name(p["name"])
        .set("tier", p["tier"])
        .set("country", p["country"])
        .set("device_type", p["device_type"])
        .set("beta_tester", p["beta_tester"])
        .build()
    )


# ===========================================================================
# 5. LIVE UPDATES  (flag change -> every open browser, no reload)
# ===========================================================================
#
# How it works:
#   a) The SDK calls on_flag_change() the instant LaunchDarkly streams a change.
#   b) on_flag_change() drops a small message into a queue for each browser
#      that currently has the page open.
#   c) Each browser holds an open GET /stream connection (Server-Sent Events)
#      and receives that message immediately.
#   d) The browser then re-fetches /api/flags and re-renders.
#
# This is why toggling a flag in the LaunchDarkly UI (or firing a trigger)
# updates the page in about a second with no refresh and no redeploy.

subscribers: "list[queue.Queue]" = []     # one queue per open browser tab
sub_lock = threading.Lock()               # subscribers is touched from several threads


def on_flag_change(change) -> None:
    """SDK callback. `change.key` is the flag that changed."""
    print(f"[LaunchDarkly] flag changed: {change.key}")
    msg = json.dumps({"flag": change.key})
    with sub_lock:
        for q in subscribers:
            q.put(msg)


# Register the callback. The SDK invokes it on its own background thread.
ld.flag_tracker.add_listener(on_flag_change)


# ===========================================================================
# 6. HTTP ROUTES
# ===========================================================================

@app.route("/")
def index():
    """Render the storefront. The persona list populates the shopper dropdown."""
    return render_template("index.html", personas=PERSONAS)


@app.route("/health")
def health():
    """
    Troubleshooting endpoint.
    {"ld_initialized": false} almost always means the SDK key is wrong,
    is the client-side ID instead of the server key, or belongs to a
    different environment than the one you created the flags in.
    """
    return jsonify(ld_initialized=ld.is_initialized(), flags=FLAGS)


@app.route("/api/flags")
def flags():
    """
    Evaluate both flags for the selected shopper.  GET /api/flags?user=priya

    ld.variation(flag_key, context, fallback) asks: "for this context, which
    variation does this flag serve?" The fallback (False) is only used if the
    flag doesn't exist or the SDK is offline - False always means the
    original, pre-feature experience.
    """
    ctx = build_context(request.args.get("user", DEFAULT_PERSONA))
    return jsonify({key: ld.variation(key, ctx, False) for key in FLAGS})


@app.route("/api/track", methods=["POST"])
def track():
    """
    Record a conversion.  POST /api/track  {"user": "priya"}

    ld.track() sends a custom event tied to the context. In LaunchDarkly you
    create a metric on the event key `hero-cta-click`, attach it to an
    experiment on `new-landing-hero`, and LaunchDarkly attributes each click
    to whichever variation that user was shown.
    """
    body = request.get_json(silent=True) or {}
    ctx = build_context(body.get("user", DEFAULT_PERSONA))
    ld.track(EVENT_HERO_CTA, ctx)
    return jsonify(ok=True)


@app.route("/stream")
def stream():
    """
    Server-Sent Events endpoint. The browser opens this once and keeps it
    open; we push a line whenever a flag changes (see section 5).
    """
    q: queue.Queue = queue.Queue()
    with sub_lock:
        subscribers.append(q)

    def generate():
        try:
            while True:
                try:
                    # Block up to 15s for a flag-change message, then send it.
                    yield f"data: {q.get(timeout=15)}\n\n"
                except queue.Empty:
                    # Nothing changed; send an SSE comment so proxies and
                    # browsers don't close the idle connection.
                    yield ": keep-alive\n\n"
        finally:
            # Browser tab closed or navigated away - stop tracking it.
            with sub_lock:
                subscribers.remove(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache"})


# ===========================================================================
# 7. ENTRYPOINT
# ===========================================================================

if __name__ == "__main__":
    # threaded=True is required: every open browser holds a long-lived
    # /stream connection, so the server must handle requests concurrently.
    #
    # PORT defaults to 5000. On macOS, AirPlay Receiver often occupies 5000;
    # set PORT=5001 in .env if the page doesn't load.
    port = int(os.environ.get("PORT", 5000))
    print(f"Sneaker Drop running on http://localhost:{port}")
    app.run(port=port, threaded=True)

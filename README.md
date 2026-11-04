# Sneaker Drop — LaunchDarkly demo (Python / Flask)

A small sneaker storefront that shows how LaunchDarkly separates **deploying code** from **releasing features**. One Flask app, one server-side SDK, two flags. Everything in the demo is driven from the LaunchDarkly dashboard — no code changes, no redeploys.

| Exercise part | What you see | Flag key |
|---|---|---|
| **Part 1 — Release & Remediate** | A "Buy now" button appears and disappears live with no reload; a `curl` to a flag trigger kills it the way a monitoring tool would | `one-click-checkout` |
| **Part 2 — Target** | A new landing hero for the QA user (individual target), Premium shoppers and beta testers (rules); everyone else keeps the old hero | `new-landing-hero` |
| **Extra credit — Experimentation** | The new hero's CTA sends a `hero-cta-click` event used as an experiment metric | `new-landing-hero` + metric |

**Time budget for a first-time reviewer:** ~3 min to run the app, ~5 min to create the flags, ~2 min to verify. Total under 10 minutes, excluding LaunchDarkly account signup.

---

## Contents

1. [Assumptions about your environment](#1-assumptions-about-your-environment)
2. [Run the app](#2-run-the-app)
3. [Create the flags in LaunchDarkly](#3-create-the-flags-in-launchdarkly)
4. [Verify it works](#4-verify-it-works)
5. [Walking through the demo](#5-walking-through-the-demo)
6. [How it works](#6-how-it-works)
7. [Project layout and endpoints](#7-project-layout-and-endpoints)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Assumptions about your environment

| Requirement | Detail | How to check |
|---|---|---|
| **Python 3.9 or newer** | Tested on 3.9 and 3.12 | `python3 --version` |
| **pip** and the `venv` module | Ship with standard Python | `python3 -m pip --version` |
| **Git** | To clone the repo | `git --version` |
| **Outbound internet** on ports 443 | The SDK streams from `stream.launchdarkly.com`; the page loads one Google Font | — |
| **A LaunchDarkly account** | Free trial: https://launchdarkly.com/start-trial | — |
| **A project + environment** in LaunchDarkly | The trial creates `Production` and `Test` by default; either works, but **use the same one everywhere** | — |
| **Flag triggers enabled** on your plan | Required for the Part 1 kill switch. Trial plans include it | Open any flag → environment ⚡ / ⋮ menu → a **Triggers** section exists |
| A free local port | Defaults to **5000**. On macOS, AirPlay Receiver often holds 5000 → use `PORT=5001` | — |
| A modern browser | Chrome, Edge, Firefox, Safari (needs `EventSource`, which they all have) | — |

Not required: Node, Docker, a database, or any LaunchDarkly CLI. Nothing is installed outside the project's own `.venv`.

**One rule to remember:** flags, triggers, SDK keys, metrics and experiments are all **per environment**. If you take the SDK key from `Production`, create everything else in `Production` too.

---

## 2. Run the app

### 2.1 Clone and install

**macOS / Linux**
```bash
git clone https://github.com/shehrozqadri/sneaker-drop.git
cd sneaker-drop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/shehrozqadri/sneaker-drop.git
cd sneaker-drop
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

This installs three packages: `flask`, `launchdarkly-server-sdk`, `python-dotenv`.

### 2.2 Get your SDK key

1. In LaunchDarkly: **Project settings → Environments → (your environment) → SDK keys**.
2. Copy the **server-side SDK key**. It starts with `sdk-`.
   - Not the **Client-side ID** (hex string, for browser SDKs).
   - Not the **Mobile key** (`mob-…`).
   This app runs the SDK on the server, so it needs the secret server key.

### 2.3 Configure

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

Open `.env` and paste the key:

```
LD_SDK_KEY=sdk-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PORT=5000
```

`.env` is git-ignored. In the code, the key is read at the block marked **`>>> REPLACE ME <<<`** near the top of `app.py` — if you prefer, `export LD_SDK_KEY=…` in your shell works too and overrides the file.

### 2.4 Start

```bash
python app.py
```

You should see `Sneaker Drop running on http://localhost:5000`. Open that URL.

**Immediately check** http://localhost:5000/health — it must return `"ld_initialized": true`. If it says `false`, the key is wrong or from a different environment; the page will also show a red banner. Fix that before continuing.

At this point the storefront renders with the **old hero** and **no "Buy now" button** — that's correct, the flags don't exist yet.

---

## 3. Create the flags in LaunchDarkly

Everything below happens in the LaunchDarkly web UI, in the **same environment** as your SDK key. Both flags are **Boolean**. Leave "client-side SDK availability" at its defaults.

### 3.1 `one-click-checkout` (Part 1)

1. **Flags → Create flag**. Name: `one-click-checkout`. The key auto-fills to the same value — confirm it is exact.
2. Flag type **Boolean**. Click **Create flag**.
3. Leave targeting **Off**. Confirm the off variation and the default rule are both `false`.

### 3.2 Trigger on `one-click-checkout` (Part 1 — remediation)

1. On the flag page, open the environment configuration: the **⚡** icon in the top-right icon row, or **⋮ → Configuration in environment**.
2. Scroll to **Triggers → + Add trigger**.
3. Trigger type **Generic trigger**. Action **Turn flag targeting off**. **Save trigger**.
4. **Copy the URL now** — LaunchDarkly hides it permanently once you leave the page. Keep it in your shell for the demo:
   ```bash
   export TRIGGER_URL="https://app.launchdarkly.com/webhook/triggers/…"
   ```
   (If you lose it, delete the trigger and create a new one.)

### 3.3 `new-landing-hero` (Part 2)

1. **Flags → Create flag**. Name: `new-landing-hero`. **Create flag**.
2. On the **Targeting** tab, add the following, top to bottom. Click the **+** between cards to insert each one.

   | # | Add via | Condition | Serve |
   |---|---|---|---|
   | 1 | **Target individuals** | context kind `user`, key `qa-sam` (type it and choose "target context with key…" if it's not listed yet) | `true` |
   | 2 | **Build a custom rule** — name it *Premium shoppers* | attribute `tier` · **is one of** · `Premium` | `true` |
   | 3 | **Build a custom rule** — name it *Beta testers* | attribute `beta_tester` · **is one of** · `true` — make sure the value is the **boolean** `true`, not the string `"true"` | `true` |
   | 4 | **Default rule** (already there) | — | `false` |

3. Flip the flag **On** at the top. **Review and save → Save changes**.

Values are case-sensitive: `Premium`, not `premium`.

### 3.4 Metric and experiment (extra credit, optional)

1. In the app, select **Priya** and click **Get early access** two or three times. This sends the event so LaunchDarkly can suggest the key.
2. **Measurement → Metrics → Create metric**: event kind **Custom**, event key `hero-cta-click`, metric definition **Occurrence (Percent)**, analysis unit **user**, higher is better. Name: `Hero CTA click`. **Create**.
3. **Experimentation → Create experiment**: name `New hero CTA`; flag `new-landing-hero`; targeting rule **Default rule**; randomize by `user`; 50/50 split with `false` as control; metric `Hero CTA click`; statistical approach **Bayesian**. **Save**, then **Start**.

> Starting the experiment replaces the default rule with a 50/50 rollout, so `alex` and `guest-4821` may be bucketed into the new hero. Assignment is deterministic per user key. **Stop** the experiment to restore the plain default rule.

---

## 4. Verify it works

With the app running and the flags created:

| Check | Expected |
|---|---|
| http://localhost:5000/health | `"ld_initialized": true` |
| Toggle `one-click-checkout` **On** → Save | **Buy now** button appears on every card within ~1 s, no reload. The dark panel logs *Flag changed: one-click-checkout* |
| Toggle it **Off** → Save | Button disappears |
| Shopper dropdown → **Sam**, **Priya**, **Jordan** | Orange "The Volt 95 drop is live" hero |
| Shopper dropdown → **Alex**, **Guest** | White "Everyday sneakers" hero (unless the experiment is running) |
| `curl -s "localhost:5000/api/flags?user=priya"` | `{"new-landing-hero": true, "one-click-checkout": false}` |

The context attributes the app sends, for reference (`kind: user`):

| key | tier | country | device_type | beta_tester | hero they should see |
|---|---|---|---|---|---|
| `qa-sam` | Standard | IN | desktop | true | new — individual target |
| `priya` | Premium | IN | mobile | false | new — Premium rule |
| `jordan` | Standard | GB | mobile | true | new — beta rule |
| `alex` | Standard | US | desktop | false | old — default |
| `guest-4821` | Free | DE | mobile | false | old — default |

---

## 5. Walking through the demo

The order I use when presenting, roughly 10 minutes. Keep the app and the LaunchDarkly tab side by side. Nothing below changes code.

**Problem.** "Engineering is asked to ship faster, but a bad release costs sales. We want releases that are instant, reversible and targeted."

**Part 1 — Release.** `one-click-checkout` is Off; the store shows only *Add to cart*. Toggle it **On → Save**. A **Buy now** button pops onto every card, no reload — the panel logs the change event. Toggle **Off → Save**: gone. That's the rollback.

**Part 1 — Incident.** Toggle it **On** again. Now simulate an alert from monitoring:
```bash
curl -X POST "$TRIGGER_URL" -H "Content-Type: application/json" \
  -d '{"eventName":"Checkout error rate > 5%","url":"https://example.com/dashboard"}'
```
Buy now disappears. No dashboard click, no deploy. The flag's **History** shows it was turned off by the trigger with that event name.

**Part 2 — Targeting.** Switch shoppers in the header: **Sam**, **Priya** and **Jordan** get the new drop hero for three different reasons (a named person, a business segment, an opt-in programme). **Alex** and **Guest** fall through to the old one. Edit a rule live — e.g. add `Standard` to the tier rule — and watch Alex flip. Turn the whole flag Off and everyone, including Sam, is back on the old hero: that's the safe rollback for a 40 000-visitor landing page.

**Extra credit — Experiment.** Show the experiment's Design tab (flag, 50/50, metric), click *Get early access* as a few shoppers, then open Results. With five users there's no significance; the point is that one `track()` call is all the code needed, and LaunchDarkly attributes every click to the variation that user saw.

---

## 6. How it works

```
LaunchDarkly ──stream──▶ Python SDK (inside Flask) ──SSE──▶ every open browser
      ▲                       │ ld.variation()  ld.track()
      └── curl trigger ───────┘
```

- **Server-side SDK.** The secret SDK key stays on the server. The browser only ever talks to Flask.
- **Instant updates.** The SDK keeps a streaming connection open and calls a listener the moment a flag changes. The server fans that out to every open tab over Server-Sent Events (`/stream`); each tab re-fetches `/api/flags` and re-renders. No polling, no reload, no redeploy.
- **Contexts.** Each shopper is sent as a `user` context with `tier`, `country`, `device_type` and `beta_tester`. All targeting decisions live in LaunchDarkly, not in code.
- **Events.** Clicking the new hero's CTA calls `ld.track("hero-cta-click", context)`, which becomes the experiment metric.

`app.py` is organised into seven commented sections — configuration, demo shoppers, LaunchDarkly client, contexts, live updates, HTTP routes, entrypoint — and `templates/index.html` mirrors that in its `<script>` block.

---

## 7. Project layout and endpoints

```
app.py                Flask server: SDK init, contexts, change listener, SSE, routes
templates/index.html  Storefront UI + a small "live flags" panel for the demo
requirements.txt      flask, launchdarkly-server-sdk, python-dotenv
.env.example          Environment variable template (copy to .env)
.gitignore            Excludes .env and .venv
```

| Route | Purpose |
|---|---|
| `GET /` | Storefront |
| `GET /api/flags?user=<key>` | Evaluate both flags for that shopper |
| `POST /api/track` `{ "user": key }` | Send the `hero-cta-click` event |
| `GET /stream` | Server-Sent Events, pushed whenever a flag changes |
| `GET /health` | `{ "ld_initialized": bool, "flags": [...] }` |

---

## 8. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Red banner, or `/health` says `false` | Wrong key type (needs the `sdk-` server key), or key from another environment. Fix `.env`, restart |
| `ModuleNotFoundError: ldclient` | The venv isn't activated, or `pip install -r requirements.txt` didn't run inside it |
| Page doesn't load on port 5000 (macOS) | AirPlay Receiver owns it. Set `PORT=5001` in `.env` |
| Flags always OFF but SDK initialized | Flag keys don't match exactly, or the flags are in a different environment than the SDK key |
| Nothing updates live | You're editing a different environment than the one the SDK key belongs to |
| Priya / Jordan don't get the new hero | Rule value typo or case (`Premium`); `beta_tester` must be the boolean `true`, not a string |
| Alex or Guest get the new hero | The experiment is running on the default rule (50/50 rollout). Stop it |
| Trigger returns 404 | URL mistyped or the trigger was deleted — create a new one |
| `NotOpenSSLWarning` on startup (macOS system Python) | Harmless. Use a Homebrew or python.org Python 3.11+ to silence it |

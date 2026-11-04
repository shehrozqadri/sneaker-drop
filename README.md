# Sneaker Drop — LaunchDarkly demo (Python / Flask)

A small sneaker storefront that shows how LaunchDarkly separates **deploying code** from **releasing features**. One Flask app, one server-side SDK, two flags.

| Exercise part | What you see | Flag key |
|---|---|---|
| **Part 1 — Release & Remediate** | A "Buy now" button appears and disappears live with no reload; a `curl` to a flag trigger kills it like a monitoring tool would | `one-click-checkout` |
| **Part 2 — Target** | A new landing hero for the QA user (individual target), Premium shoppers and beta testers (rules); everyone else keeps the old hero | `new-landing-hero` |
| **Extra credit — Experimentation** | The new hero's CTA sends a `hero-cta-click` event used as an experiment metric | `new-landing-hero` + metric |

---

## How it works

```
LaunchDarkly ──stream──▶ Python SDK (Flask process) ──SSE──▶ every open browser
      ▲                      │ ld.variation()  ld.track()
      └── curl trigger ──────┘
```

- **Server-side SDK** (`launchdarkly-server-sdk`). The secret SDK key never reaches the browser.
- **Instant updates.** The SDK's `flag_tracker` listener fires the moment a flag changes; the server fans that out to open tabs over Server-Sent Events (`/stream`), and the page re-evaluates its flags — no reload, no redeploy.
- **Contexts.** Each demo shopper is sent as a `user` context with `tier`, `country`, `device_type` and `beta_tester` attributes. All targeting decisions live in LaunchDarkly, not in code.
- **Events.** Clicking the new hero's CTA calls `ld.track("hero-cta-click", context)`.

```
app.py               Flask server: SDK init, contexts, change listener, SSE, routes
templates/index.html Storefront UI + a small "live flags" panel for the demo
requirements.txt
.env.example         Environment variable template
```

---

## Assumptions

- Python 3.9+ with `pip`, and internet access (SDK streaming; one Google Font).
- A LaunchDarkly account. Free trial: https://launchdarkly.com/start-trial
- **Flag triggers** are available on your plan (check: open any flag → environment ⚡ / ⋮ menu → look for a *Triggers* section).
- Flags, triggers, SDK keys and experiments are all **per environment**. Everything below must be done in the same environment the SDK key belongs to.

---

## 1. Run the app (≈ 3 minutes)

```bash
git clone <this-repo> && cd sneaker-drop
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then edit .env
python app.py                                         # http://localhost:5000
```

**Where to paste the SDK key:** `.env` → `LD_SDK_KEY=sdk-…`. It is read in `app.py` at the block marked `>>> REPLACE ME`.

Use the **server-side SDK key** (starts with `sdk-`) from *Project settings → Environments → SDK keys*. Not the client-side ID, not the mobile key.

Sanity check: http://localhost:5000/health should return `"ld_initialized": true`. If it is `false`, the page shows a red banner.

> macOS: if port 5000 is taken by AirPlay Receiver, set `PORT=5001` in `.env`.

---

## 2. Create the flags (≈ 5 minutes)

Both flags are **Boolean**, created in the same environment as your SDK key. No client-side availability changes are needed.

### `one-click-checkout` — Part 1
1. **Flags → Create flag**, name `one-click-checkout` (key auto-fills). Create.
2. Leave targeting **Off**. Off variation and default rule should both be `false`.

### Trigger on `one-click-checkout` — Part 1 remediation
1. On the flag, open the environment configuration (⚡ icon or ⋮ → *Configuration in environment*).
2. **Triggers → + Add trigger** → type **Generic trigger**, action **Turn flag targeting off** → Save.
3. **Copy the URL now** — it is hidden once you leave the page. Keep it in your shell:
   ```bash
   export TRIGGER_URL="https://app.launchdarkly.com/webhook/triggers/…"
   ```

### `new-landing-hero` — Part 2
1. **Flags → Create flag**, name `new-landing-hero`. Create.
2. On the Targeting tab, add in this order (click **+** between cards):
   | # | Type | Condition | Serve |
   |---|---|---|---|
   | 1 | **Target individuals** | context kind `user`, key `qa-sam` | `true` |
   | 2 | **Custom rule** "Premium shoppers" | `tier` *is one of* `Premium` | `true` |
   | 3 | **Custom rule** "Beta testers" | `beta_tester` *is one of* `true` (boolean, not the string `"true"`) | `true` |
   | 4 | **Default rule** | — | `false` |
3. Toggle the flag **On** → **Review and save**.

Contexts the app sends (`kind: user`):

| key | tier | country | device_type | beta_tester | hero they should see |
|---|---|---|---|---|---|
| `qa-sam` | Standard | IN | desktop | true | new — individual target |
| `priya` | Premium | IN | mobile | false | new — Premium rule |
| `jordan` | Standard | GB | mobile | true | new — beta rule |
| `alex` | Standard | US | desktop | false | old — default |
| `guest-4821` | Free | DE | mobile | false | old — default |

### Metric + experiment — extra credit
1. In the app, pick **Priya** and click **Get early access** a couple of times so the event key is known to LaunchDarkly.
2. **Measurement → Metrics → Create metric**: event kind **Custom**, event key `hero-cta-click`, definition **Occurrence (Percent)**, unit **user**, higher is better. Name it `Hero CTA click`.
3. **Experimentation → Create experiment**: flag `new-landing-hero`, targeting rule **Default rule**, randomize by `user`, 50/50 split with `false` as control, metric `Hero CTA click`, Bayesian. Save, then **Start**.

> Starting the experiment turns the default rule into a 50/50 rollout, so `alex` and `guest-4821` may now be bucketed into the new hero. Assignment is deterministic per user key. **Stop** the experiment to restore the plain default rule when you want to show Part 2 cleanly; start a new iteration before showing experiment results.

---

## 3. Demo script (≈ 10 minutes)

Keep the app and the LaunchDarkly tab side by side. Nothing below changes code.

**Problem.** "Engineering is asked to ship faster, but a bad release costs sales. We want releases that are instant, reversible and targeted."

**Part 1 — Release.** `one-click-checkout` is Off; the store shows only *Add to cart*. Toggle it **On** → Save. A **Buy now** button pops onto every card within a second, no reload — the panel logs the change event. Toggle **Off** → gone. That's the rollback.

**Part 1 — Incident.** Toggle it **On** again. Now simulate an alert from monitoring:
```bash
curl -X POST "$TRIGGER_URL" -H "Content-Type: application/json" \
  -d '{"eventName":"Checkout error rate > 5%","url":"https://example.com/dashboard"}'
```
Buy now disappears. No dashboard click, no deploy. The flag's **History** shows it was turned off by the trigger with that event name.

**Part 2 — Targeting.** Switch shoppers in the header: **Sam**, **Priya** and **Jordan** get the new drop hero for three different reasons (a named person, a business segment, an opt-in programme). **Alex** and **Guest** fall through to the old one. Edit a rule live — e.g. add `Standard` to the tier rule — and watch Alex flip. Turn the whole flag Off and everyone, including Sam, is back on the old hero: that's the safe rollback for a 40 000-visitor landing page.

**Extra credit — Experiment.** Show the experiment's Design tab (flag, 50/50, metric), click *Get early access* as a few shoppers, then open Results. With five users there's no significance; the point is that one `track()` call is all the code needed, and LaunchDarkly attributes every click to the variation that user saw.

---

## Endpoints

| Route | Purpose |
|---|---|
| `GET /` | Storefront |
| `GET /api/flags?user=<key>` | Evaluate both flags for that shopper |
| `POST /api/track` `{ "user": key }` | Send `hero-cta-click` |
| `GET /stream` | Server-Sent Events: pushed whenever a flag changes |
| `GET /health` | `{ "ld_initialized": bool }` |

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Red banner / `/health` false | Wrong key type (needs the `sdk-` server key) or key from another environment |
| Flags always OFF but SDK initialized | Flag keys don't match exactly, or flags are in another environment |
| Nothing updates live | You're editing a different environment than the SDK key |
| Priya / Jordan don't get the new hero | Rule values are case-sensitive (`Premium`); `beta_tester` must be boolean `true` |
| Alex gets the new hero | Experiment is running on the default rule — stop it |
| Trigger returns 404 | URL mistyped or trigger deleted — create a new one |

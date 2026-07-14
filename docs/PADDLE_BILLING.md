# Paddle Billing — How Payments Work in Clip Insights

This document explains the payment integration end to end: what Paddle is, how
a subscription flows through the system, and how to operate it (sandbox and
live). Plan *limits* are documented separately in `PLANS_AND_PRICING.md`.

---

## 1. What Paddle is (and why we use it)

Paddle is a **Merchant of Record (MoR)**: legally, Paddle sells the
subscription to the customer and then pays us out. That means Paddle — not us —
handles card processing, global sales tax/VAT, fraud, chargebacks, and
receipts. We never see card numbers, so there is no PCI burden. Pricing is
5% + $0.50 per transaction, all-in. Payouts go to Payoneer/bank (works from
Pakistan, where Stripe is unavailable — the reason Paddle was chosen).

Two independent environments exist:

| | Sandbox | Live |
|---|---|---|
| Dashboard | https://sandbox-vendors.paddle.com | https://vendors.paddle.com |
| API | https://sandbox-api.paddle.com | https://api.paddle.com |
| Money | fake (test cards) | real |

`PADDLE_ENV` selects which one the backend talks to.

## 2. The pieces on our side

| Piece | Where | Role |
|---|---|---|
| Payment provider | `integrations/payment/paddle.py` (behind `get_payment()`) | All Paddle API calls + webhook signature verification |
| Catalog map | `billing.PaddlePlanMap` | plan slug ↔ Paddle product/price ids (+ annual price) |
| Subscription mirror | `billing.Subscription` | Paddle-side state per user (ids, status, period end) |
| Entitlement | `plans.UserPlan` | what the limit system reads; upserted by webhooks |
| Endpoints | `billing/urls.py` → `/api/billing/*` | catalog, checkout config, subscription, cancel, webhook |
| Catalog sync | `manage.py setup_billing` | creates Paddle products/prices for paid plans |
| Browser side | web `src/services/paddle.js` + `Pricing.jsx` | loads Paddle.js v2, opens the overlay checkout |

Plans themselves (limits, monthly price) are owned by the `plans` app; billing
never duplicates them.

## 3. The full payment cycle

```
        ┌───────────┐   1. GET /api/plans/ + /api/billing/catalog/
        │ Pricing   │◄─────────────────────────────────────────── backend
        │ page      │
        │ (web app) │   2. POST /api/billing/checkout/ {plan, cycle}
        │           │──────────────────────────────────────────►  backend
        │           │◄── {environment, client_token, price_id,
        │           │     email, user_id}
        │           │
        │           │   3. Paddle.js opens the OVERLAY CHECKOUT
        │           │──────────────────────────────────────────►  Paddle
        └───────────┘      (card entry happens on Paddle's iframe,
                            never touches our servers)
                                        │
                       4. customer pays │ Paddle creates the
                                        ▼ subscription
        ┌───────────┐   5. webhook: subscription.created/updated/canceled
        │  backend  │◄─────────────────────────────────────────── Paddle
        │           │      (HMAC-signed; custom_data.user_id tells us who)
        │           │
        │           │   6. billing.Subscription upserted (mirror)
        │           │      plans.UserPlan upserted (entitlement)
        └───────────┘
                       7. limits system reads UserPlan → user has Pro/Premium
```

Step by step:

1. **Pricing page** renders plans from `/api/plans/` (limits, monthly price)
   and `/api/billing/catalog/` (annual price, which plans are purchasable).
2. **Checkout config** — the signed-in user picks a plan + cycle; the backend
   returns the Paddle `price_id`, the public `client_token`, the environment,
   and the user's id/email. No server-side transaction is created.
3. **Overlay checkout** — Paddle.js (loaded from Paddle's CDN) opens a hosted
   checkout inside the page. We pass `customData: {user_id}` — this is the
   thread that later ties the webhook back to our user — and the customer's
   email to prefill. The card form is Paddle's; our origin never sees PANs.
4. **Payment** — Paddle charges the card, calculates/remits tax, creates a
   `subscription` object with a `current_billing_period`.
5. **Webhook** — Paddle POSTs events to `/api/billing/webhook/`. We verify the
   `Paddle-Signature` header (HMAC-SHA256 of `ts:body` with the webhook
   secret) and ignore anything that fails. Unsigned/forged requests can't
   grant plans.
6. **Projection** — for `subscription.*` events we look up the user from
   `custom_data.user_id` and the plan from the price id, then upsert:
   - `billing.Subscription` — status, billing cycle, `current_period_end`,
     `cancel_at_period_end` (from `scheduled_change`);
   - `plans.UserPlan` — the entitlement. `expires_at = period end + 2 days`
     grace, so a slightly late renewal webhook never bounces a paying user to
     free. On `canceled`/`paused`/`past_due` the user reverts to free.
7. **Enforcement** — nothing else changes: `plans.services.get_plan_for()`
   already resolves the user's plan on every gated request.

### Renewal
Paddle charges automatically each period and sends `subscription.updated` with
the new `current_billing_period.ends_at`; step 6 extends `expires_at`. If a
renewal charge fails, Paddle retries (dunning) and the status becomes
`past_due` → user reverts to free until payment succeeds.

### Cancellation
`POST /api/billing/cancel/` calls Paddle's *cancel at next billing period*.
Paddle replies with `scheduled_change: cancel` (we set
`cancel_at_period_end=True` so the UI can say "ends on …"), keeps the
subscription `active` until the paid period ends, then sends
`subscription.canceled` → user reverts to free. The user keeps what they paid
for; no proration surprises.

### Upgrades
Buying a different plan opens a new checkout (simplest correct flow). The new
subscription's webhook overwrites the entitlement.

## 4. Environment variables

```
PADDLE_ENV=sandbox            # or: live
PADDLE_API_KEY=pdl_sdbx_...   # Developer Tools → Authentication → API keys (secret)
PADDLE_CLIENT_TOKEN=test_...  # same page → Client-side tokens (public, used by the browser)
PADDLE_WEBHOOK_SECRET=pdl_ntfset_...  # Developer Tools → Notifications → destination secret
# PAYMENT_PROVIDER defaults to "paddle"; tests force "noop" in conftest.py
```

## 5. Operating runbook

### One-time setup (per environment)
1. Create the three credentials above in the Paddle dashboard and put them in
   `.env`.
2. `uv run python manage.py setup_billing` — creates one Paddle **product** per
   paid plan and two **prices** (monthly = `plans.Plan.monthly_price_usd`;
   annual = 10× monthly, i.e. two months free) and stores the ids in
   `PaddlePlanMap`. Idempotent: reruns only create what's missing.
3. Create a **webhook destination** (Developer Tools → Notifications) pointing
   at `https://<backend-host>/api/billing/webhook/`, subscribed to
   `subscription.created`, `subscription.updated`, `subscription.canceled`
   (extra events are ignored harmlessly). Copy its secret into `.env`.

### Testing a purchase in sandbox
- Card `4242 4242 4242 4242`, any future expiry, any CVC.
- Webhooks need a public URL. For local dev, tunnel the backend
  (`ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000`) and
  point the sandbox webhook destination at the tunnel URL. Without a tunnel
  the payment succeeds but the plan never activates locally — that's the
  webhook not arriving, not a bug.
- Paddle retries failed webhook deliveries with backoff for ~3 days, and the
  dashboard (Notifications → Logs) lets you replay any event manually.

### Going live (checklist)
1. Paddle live account approved (website review).
2. New live API key / client token / webhook secret in production env;
   `PADDLE_ENV=live`.
3. Run `setup_billing` once against production (creates the live catalog).
4. Webhook destination → production backend URL.
5. Payout method (Payoneer/bank) configured in the live dashboard.

## 6. Security properties worth knowing

- The **client token is public** by design; it can only open checkouts.
- The **API key is secret**; it can manage the catalog and subscriptions.
- Webhooks are trusted **only** after HMAC verification; without the secret an
  attacker cannot mint themselves a Premium plan.
- Entitlement comes exclusively from webhooks (server-to-server). The
  browser's "checkout completed" event is used for UX only (toast + refresh),
  never to grant a plan.

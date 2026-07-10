# Plans, Limits & Self-Sustainability Analysis

How the seeded plan limits were derived, and the cost model behind them. The goal of this
first pass is **rough self-sustainability**: every paid tier covers its own worst-case
variable cost at realistic utilization, and the free tier is a bounded acquisition cost.
Final pricing needs the planned market research; all numbers are editable per-plan in the
Django admin (`Plans → Plan`) without code changes.

## 1. Unit cost model (variable costs per action)

| Action | Assumptions | Est. cost |
|---|---|---|
| Summary + key points (one request) | Gemini Flash: ~8k input tokens @ $0.10/M, ~1k output @ $0.40/M | **~$0.0012** (scales with `transcript_token_budget`: 16k ctx ≈ $0.0024, 32k ≈ $0.0048) |
| Chat message | RAG keeps input small: ~2.5k input + ~0.5k output tokens (+ negligible embedding cost, amortized once per video) | **~$0.0005** |
| Storage | S3 ~$0.023/GB-month | **~$0.002 per 100 MB-month** |
| Notes / screenshots / PDF export | Stored in the user's browser (IndexedDB), generated client-side | **$0** — this is why guests get them |

## 2. Seeded plans and worst-case monthly cost

"Worst case" = a user maxing every daily limit 30 days straight (in practice p95 users sit
far below; 20–40% utilization is a generous planning figure).

| Limit | Guest | Free | Pro ($5/mo) | Premium ($12/mo) |
|---|---|---|---|---|
| Daily summaries | 0 | 5 | 25 | 50 |
| Daily chat messages | 0 | 15 | 100 | 200 |
| Max chat query (chars) | 0 | 1,000 | 2,000 | 4,000 |
| Transcript token budget | 0 | 8,000 | 16,000 | 32,000 |
| Storage | 0 | 100 MB | 1 GB | 5 GB |
| Max file size | 0 | 10 MB | 25 MB | 50 MB |
| Max note length (chars) | 500 | 1,000 | 5,000 | 10,000 |
| Notes per video | 10 | 100 | 300 | 1,000 |
| Screenshots per video | 10 | 40 | 100 | 200 |

**Cost ceilings (30-day worst case):**

- **Guest — $0.** Only client-side features. Their purpose is conversion: every gated
  action shows a "sign up free" prompt.
- **Free — ≈ $0.41 worst case** (summaries $0.18 + chat $0.23 + storage <$0.01);
  typical usage ≈ $0.10/mo. A bounded, cheap acquisition funnel.
- **Pro — ≈ $3.30 absolute worst case** (summaries 25×30×$0.0024 = $1.80 + chat
  100×30×$0.0005 = $1.50) if both are simultaneously maxed; at a realistic 30%
  utilization ≈ **$1/mo cost vs $5 revenue** → ~80% gross margin. Simultaneous 100%
  utilization of all limits stays profitable by design (the limits *are* the cost
  ceiling).
- **Premium — ≈ $10.30 absolute worst case** (summaries $7.20 + chat $3.00 + storage
  $0.12); at 10–15% typical utilization ≈ **$1.50/mo cost vs $12 revenue**. A
  month-long 100% abuser still leaves margin; if abuse materializes, tighten
  `daily_summaries` in the admin or add a monthly hard cutoff when Paddle
  subscription state lands.

Fixed costs (hosting, DB, email) are shared and small at current scale; roughly 40–60
Pro subscribers or 20 Premium subscribers cover them with margin to spare.

## 3. Where each limit is enforced

| Limit | Enforced | How |
|---|---|---|
| Daily summaries / chats | Backend | `plans.services.enforce_daily_limit` — rolling 24h count of `UsageEvent` rows; structured 429 with `{code, reason, message, cta}`; charged only on success |
| Chat query length | Backend | truncated (not rejected) to `max_chat_query_chars`; clients warn on paste |
| Transcript token budget ("video token limit") | Backend + client | `GET /api/videos/tokenlimit/` now returns the *caller's plan* budget; server also truncates defensively |
| Storage + per-file size | Backend | checked before S3 upload; cap comes from the plan (replaces `User.allocated_space`) |
| Note length / notes per video / screenshots per video | Client (extension) | data never reaches the server (IndexedDB); values are still served from `GET /api/plans/` so they stay backend-managed config |
| AI access for guests | Backend | AI endpoints are `IsAuthenticated` → 401 → clients show the sign-up prompt |

## 4. Integration contract for the payments work (Paddle)

The payments integration only needs to upsert one row on subscribe / renew / cancel:

```python
from plans.models import Plan, UserPlan
UserPlan.objects.update_or_create(
    user=user,
    defaults={"plan": Plan.objects.get(slug="pro"), "expires_at": period_end},
)
```

- No row (or `expires_at` in the past, or an inactive plan) ⇒ the user is `free`.
- Cancel = set `expires_at` to the paid-through date; the fallback is automatic.
- Everything else (enforcement, counters, client payloads) picks the change up on the
  next request — there is no cache to invalidate.

## 5. Follow-ups for the detailed pricing pass

- Calibrate token estimates against real `UsageEvent` volume once there is traffic
  (add per-event token/cost columns then — the ledger table is already in place).
- Consider a monthly hard budget cutoff per user (Zayg's `hard_monthly_cutoff_usd`
  pattern) once subscription lifecycle events exist to reset it against.
- Regional pricing and annual discounts are Paddle-side concerns.

---
name: finding-your-first-customer
description: "Discover urgent product ideas from real customer workarounds, identify what to build by finding urgent customer problems and validate demand with paying customers before you build."
platforms: [linux, macos, windows]
---

# Finding First Customer
### A Positive Deviance Approach

## When to use

Load when the user wants to find product ideas, validate startup concepts, identify underserved markets, run product discovery, find first customers, or evaluate whether a problem is worth building. Trigger on: product idea, what should I build, is this worth building, find product opportunities, validate idea, first paying customer, first customer, zero to one, find customers, how do I get my first user, or exploring a market to enter.

## Core Principle

Zero-to-one products succeed by replicating deviant behaviors — users already solving a problem themselves, ineffectively. Their behavior is proof of urgency. The workaround IS the thesis. Find it. Charge for it manually. Then build.

**Fastest path to first paying user:**
`observe workaround → identify deviant → concierge transaction → charge card → build`

Not: ideate → prototype → launch → find users.

---

## Rules (Apply All)

- `paid_workaround_exists > workaround_exists > problem_acknowledged`
- `time_spent_on_workaround > stated_willingness_to_pay`
- `urgency_now > potential_future_need`
- `one_charged_card > ten_enthusiastic_signups`
- `independent_parallel_invention > single_power_user_workaround`
- `concierge_before_code` — always
- `inefficient_behavior_is_signal_not_flaw`

---

## Discovery Process

### Step 1: Source Inputs

Only use behavioral evidence. Reject stated preferences.

**Valid sources:**
- Forum threads (Reddit, HN, niche communities) where people describe their manual process
- Support tickets showing workarounds users built themselves
- Twitter/X threads where someone is clearly doing something manually that shouldn't be manual
- Job postings that describe a role doing something that should be automated
- Observed workflows (screen recordings, walkthroughs, demos)
- User interviews focused on *what they did last week*, not *what they want*

**Reject:**
- Market research reports
- TAM/SAM/SOM estimates
- Survey stated preferences
- User enthusiasm without payment attempt
- Waitlist signups without credit card
- Problems users acknowledge but don't act on

---

### Step 2: Run the Required Tests

#### Test 1: Workaround Exists (REQUIRED — stop if no)

Is there an observable behavior where users are solving this problem manually?
- Spreadsheets, DMs, copy-paste, numbering tweets, hiring a VA, emailing files to themselves
- If no observable workaround exists: **stop — the problem isn't urgent enough**

#### Test 2: Paid Workaround Tier

Classify the workaround type. Higher tier = stronger signal.

| Tier | Type | Example | WTP Signal |
|------|------|---------|-----------|
| 3 | **Paid workaround** | Hiring consultant, buying worse product | Direct — this is your price floor |
| 2 | **Embarrassment-cost workaround** | Emailing nudes for deletion, manual data entry in front of clients | Strong emotional unlock |
| 1 | **Free high-friction workaround** | Numbering tweets manually, copy-pasting between apps | Proves urgency, weaker WTP |

If `paid_workaround = true` → **build_now override** — skip urgency scoring, go straight to concierge.

#### Test 3: Independent Parallel Invention

Have multiple people built the *same* workaround independently, without knowing each other?

- Pattern across ≥3 independent users = market signal
- Single power user with unique setup = feature request, not product
- Ask: "Did this person invent this workaround or copy it from someone?"

#### Test 4: Urgency Gate (Binary — not a scale)

> "Is this user solving this problem *this week*, not someday?"

- Yes → proceed
- No → discard or reframe as roadmap item

Do not score urgency 1–10. That invites rationalization. It's yes/no.

#### Test 5: Switching Friction

How hard is it to switch from the workaround to your product?

- **Pure subtraction** (same behavior, less friction) → fast conversion
- **Behavior change required** → slow conversion, needs 10x delta
- **Workflow-embedded workaround** (e.g., Airtable hack that 5 people use) → high switching cost, needs strong pull

#### Test 6: Build vs Workaround Delta

| Delta | Signal |
|-------|--------|
| 10x better | Strong pull — users switch without being sold |
| 2x better | Weak pull — needs marketing |
| Parity | No reason to switch — stop |

---

### Step 3: Concierge Gate (Before Any Code)

**This is the fastest path to first paying user.**

Before writing a line of code:
1. Identify one deviant
2. Offer to deliver the outcome *manually*
3. Charge them for it
4. Success condition = credit card charged

If you can't charge for a manual version, your product framing is wrong — not the market.

Script template:
> "I noticed you've been [workaround behavior]. I can [outcome] for you manually by [date] for $[price]. Want me to handle it?"

Do not ask "would you use this?" That is not a charge. That is a survey.

---

## Required Outputs

### 1. Deviance Table

| # | Observed Behavior | Platform/Context | Workaround Method | Workaround Tier | Cost of Workaround |
|---|---|---|---|---|---|
| 1 | | | | 1/2/3 | time + money + embarrassment |

Quantify where possible. "2 hrs/week × $50/hr = $100/week" beats "annoying."

### 2. First Customer Profile

For each deviant identified:

```
Who they are:        [specific description, not "SMBs" or "developers"]
Where to find them:  [exact subreddit, community, job board, hashtag]
Why they care now:   [what changed recently that makes this urgent]
DM/reply script:     [exact message to send today offering the concierge]
Offer framing:       ["I'll do X manually for $Y by Friday" — not a survey invite]
```

### 3. Workaround Cost Calculation

```
Time cost:         X hrs/week × hourly rate = $/week
Money cost:        tools/services they're paying for workaround
Embarrassment:     describe the social/reputational friction
Total weekly cost: $X
Annualized:        $Y  ← this is your price ceiling for annual contract
```

### 4. Verdict

| Verdict | Condition | Action |
|---------|-----------|--------|
| **CHARGE NOW (MANUALLY)** | Paid workaround exists, deviant identified, concierge feasible | Send the DM today, charge before building |
| **INTERVIEW AND CHARGE** | Workaround exists, deviants found, no paid signal yet | Talk to 3 deviants this week, attempt charge at end of each call |
| **WATCH AND WAIT** | Parallel invention pattern emerging, <3 independent cases | Monitor for 30 days, set a trigger to recheck |
| **DISCARD** | No observable workaround, or free low-friction workaround only | Kill — move to next idea |

---

## Worked Example Skeleton

**Domain:** [fill in]

**Observed workaround:** [what people are doing manually]

**Where found:** [subreddit / thread / support ticket]

**Workaround tier:** [1/2/3]

**Independent parallel invention:** [yes/no — how many found?]

**Urgency gate:** [this week yes/no]

**Switching friction:** [pure subtraction / behavior change]

**10x delta achievable:** [yes/no — how]

**Concierge feasibility:** [can I do this manually today for $X?]

**First DM:** [exact message]

**Verdict:** [CHARGE NOW / INTERVIEW AND CHARGE / WATCH AND WAIT / DISCARD]

---

## What This Skill Does Not Do

- TAM estimates
- Competitive landscape analysis as primary signal
- Roadmap planning
- Pricing strategy (beyond workaround cost as floor/ceiling)
- GTM beyond first 10 customers

For scale, use a different framework. This skill terminates at first paying user.

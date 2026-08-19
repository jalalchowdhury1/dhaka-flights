# AGENTS.md — dhaka-flights trip tracker

> Read this first. `README.md` / `JALAL_READ.md` are Jalal's plain-English docs — leave
> them alone unless asked. This file is the single LLM source of truth for this repo.

## 1. What this is

Nightly price tracker for **ONE** trip (2 adults + 1 child with seat) —
narrowed 2026-07-25 from "price every variant" to "price the trip he's buying",
reshaped 2026-08-01 (**Bali OUT** — "I don't like the tail risk of dengue" —
Bangkok in, the 5 Marriott nights move there):

> **BOS → Istanbul (2 nights) → Dhaka (≤29 days; 30-day visa) → Bangkok
> (5 nights; Marriott 5th-night-free) + Singapore (2 nights), IN WHICHEVER
> ORDER IS CHEAPER → BOS, home by Feb 7, 2027.**

Both city orders are priced every night; the cheaper complete trip headlines
and the loser is surfaced as `other_order` with its Δ (never hidden). It buys
as **two purchases**, and everything in the code is named for them:

| | what | how it's scraped |
|---|---|---|
| **Ticket ①** | BOS→IST + IST→DAC + **{SIN or BKK}→BOS**, one multi-city ticket per order | `STOPOVER_SEARCHES` = `TICKET1_SIN_RETURN` + `TICKET1_BKK_RETURN` (kind `stopover2`, `ret_city` keys the order) |
| **Ticket ②** | DAC→BKK→SIN (BKK-first) or DAC→SIN→BKK (SIN-first) — one multi-city ticket **or** two one-ways, whichever is cheaper | `TICKET2_SEARCHES` (order-tagged) + the four `LEGS` |

Every night at midnight it scrapes **30 searches ≈ 20–24 min** (2 Ticket ① +
7 Ticket ② pairs + 18 one-way leg×dates + the 3-search 🌴 Bali watch — the
budget is Jalal's, 2026-08-01 evening: "no more than 25 minutes" then "you
can get it up to 30 searches if it helps you"),
prices both orders, self-checks, writes a Google Sheet, Telegrams the result
(with per-leg baggage + same-date alternatives + the 🏨 hotel plan), and
publishes `site/data.json` for **dhaka-flights.vercel.app**.
Spec: `docs/superpowers/specs/2026-08-01-bangkok-singapore-swap-design.md`.

**🔎 Nightly self-verification (`verify.py`, 2026-08-01 evening — "once done
verify. Multiple times. take different perspectives."):** after the payload is
built and BEFORE anything is sent, three independent perspectives run every
night: (1) RECOMPUTE — a brute-force cheapest-strict-shape search written
independently of combo.py must agree with each order's total, and a flagged
day must truly have no strict-shape option; (2) ARITHMETIC — ①+②=total,
other-order/Bali Δs, history mirror, budget strictly cheaper; (3) CONTRACT —
unflagged days must be 2 IST / 5 BKK / 2-4 SIN and the hotel card must match
the flights. Findings join the 🧪 self-check block in Telegram + the site;
a clean pass adds a "🔎 independent re-check ✓" footer. verify.py must stay
INDEPENDENT of combo.py — its value is being a second implementation.

**Speed rules (2026-08-01 evening — protect the 25-min cap):**
1. ONE browser session per RUN (`scraper._ensure_session`): the old
   per-search stop→env→open cycle cost ~35-40s each. Blank pages/exceptions
   call `_session_dirty()` so the existing retry paths restart the browser;
   `end_session()` is called once by the runners after all scraping. Never
   reintroduce a per-search `browse stop`.
2. Adding a search costs ~45-60s of nightly runtime — anything new must fit
   the cap or displace something.

**🌴 Bali comparison watch (2026-08-01 evening, Jalal: "keep another tab open
for the original bali trip. i want to be able to compare"):** the RETIRED
original trip (BOS→IST 2n→DAC→SIN 2n→Bali 5n→BOS) is still scraped nightly —
`scraper.scrape_bali_watch()` runs LAST (a throttled night degrades the
benchmark before the product): `ISTANBUL2_SEARCH` (DPS-return Ticket ①) +
the two `BALI_WATCH_PAIRS` one-ticket middles = 3 searches (slimmed from 11
for the cap; no one-way middles — a consistent yardstick beats exhaustive
coverage for a benchmark). The trip is built by the retired
`combo.main_trip_bali`, rides in the payload as `bali` (with
`delta_vs_main`), history key `bali_total`, Sheet column "🌴 Bali $", a 🌴
Telegram line, and the site's "🌴 Bali (old)" tab; the chart's Bali line
stitches pre-swap `main_total` history to nightly `bali_total`. It is a
BENCHMARK, not a bookable product: no alerts fire on it, and sanity raises
ONE warning when it's missing (never per-search noise).

**Hotel-content convention (2026-08-02, Jalal: "make that standard"):** any
hotel/resort table or card on the SITE must show the **offset %** — credits
the user will actually use ÷ (room + ~12% tax) — with the July deal-
calculator bands (≥70% book now · 50–70% solid · <50% wait). Keep the
assumption line (which credits were counted) next to every table.

**Nightly hotel rates (`hotel_rates.py` + `run_hotel_rates.py`, 2026-08-03).**
Jalal caught the IST/SIN shortlist showing rates that no longer matched
("Ritz carlton is more like $500 a night"): they had been hand-researched on
2026-08-01 and frozen into the HTML with no provenance, and by 2026-08-03 two
were ~30% low (Ritz-Carlton Istanbul $314→$425, Sanasaryan Han $270→$348),
which pushed both out of the ≥70% "book now" band they were being recommended
from. Rules now:
1. **No hotel number lives in the HTML.** The tables render from
   `site/hotel_rates.json`, and every rate carries its own `checked` date;
   anything older than 3 days is badged on the row.
2. **What is tracked is the PUBLIC nightly rate incl. fees** (Google Hotels,
   the real stay dates). The rates the card play books — Amex FHR and Chase
   Edit — are behind CARDHOLDER LOGINS and are not scrapable from here, ever.
   The site says so next to the table; treat the public rate as a drift alarm
   and an offset denominator, not as the booking rate.
3. **`ts=`, never `checkin=`/`checkout=`.** This is the single most important
   rule here. The plain date params are honoured only by a browser that
   already carries Google session state; in a clean automated session they are
   DROPPED and the page silently prices TONIGHT while still rendering a
   believable number (verified 2026-08-03: a Jan-2027 request came back
   showing "Sun, Aug 9"). `hotel_rates.ts_param()` builds Google's protobuf
   `ts` parameter — checkin/checkout/guests/currency — which binds with no
   cookies at all. A test pins it byte-for-byte against a known-good URL; if
   that test ever fails, every rate silently becomes tonight's.
4. **The date guard is the backstop.** A scrape is accepted ONLY when the page
   proves the property AND the requested dates, read from Google's own
   check-in/check-out fields; otherwise the previous rate is kept with its
   ORIGINAL date. Keep queries SHORT — "Sanasaryan Han Istanbul" resolves,
   "Sanasaryan Han Luxury Collection Istanbul" returns no results.
5. **Read with `browse eval`, never `browse snapshot`.** A Google Hotels a11y
   snapshot is ~5 MB and repeatedly blew the 30 s CLI timeout; the eval
   returns ~150 bytes. carmax-scraper learned the same on kbb.com. The JS is
   flattened to ONE line and shell-quoted before it runs, so it must contain
   no line comments and no apostrophes — a line comment silently swallows the
   rest of the function and every property returns "no page payload" (this
   exact bug shipped and was caught by a live run). A test enforces both.
6. **Scrape from Browserbase, not from this house.** `run_hotel_rates.py`
   switches the CLI to `browse env remote` (key in the gitignored `.env`), so
   hotel traffic leaves from Browserbase residential IPs and the home IP is
   never spent — Google slow-walked it on 2026-08-03 after ~10 hotel searches,
   and that same IP is what the midnight flight run depends on. This is the
   first repo in the ecosystem to actually wire Browserbase in; carmax-scraper
   and sentiment-scraper both document it as an unused escape hatch.
6b. **The free tier is 60 browser-minutes per CALENDAR month, and demand
   slightly EXCEEDS it.** The counter resets on the 1st (verified 2026-08-16:
   August's sessions summed to 60.91 min against a usage endpoint reporting 61
   — monthly, not lifetime). A full 8-property remote run bills **2.25-2.32 min
   measured**, so 30 nights ≈ 69 min against a 60-min cap. Nightly is what
   Jalal wants ("i want to see every miniscule change"), so the shortfall is
   paced, not eliminated — see 6d. A remote session bills by WALL-CLOCK, so
   every idle second is money: `browse eval` is POLLED, never slept on
   (`_wait_for_page`), and the inter-property gap is mode-aware (6e).
   **Before adding any sleep to this path, price it: 1 s × 8 properties × 30
   nights = 4 min/month.** `browserbase_usage()` reads the live counter over
   plain REST (zero browser minutes) and prints `used/cap` every run — but it
   LAGS (it still read 0 after three runs on 2026-08-16), so treat it as a
   coarse signal and never as a precise ledger.
6d. **Pacing (`should_conserve`) picks WHICH nights fall back, and that matters
   more than how many.** Letting the quota simply run dry puts every local
   night in one consecutive block at month-end, and a multi-night burst of
   hotel searches from the home IP is exactly the shape Google slow-walked on
   2026-08-03; a single isolated night is not. So the choice is random, weighted
   by how far behind pace the month is, which scatters ~4 local nights through
   the month and self-corrects (a local night spends no quota, putting the next
   night back ahead of pace). `EST_RUN_MINUTES` is set ABOVE the measured max on
   purpose — overestimating costs a few needless local nights, underestimating
   dries the quota out mid-month. Re-derive it after a full month of real data;
   n=2 is thin. Tests: `tests/test_hotel_pacing.py`.
6e. **The inter-property gap is per-mode (`JITTER`), because the same pause is
   expensive-and-pointless on one and free-and-valuable on the other.** Remote
   1-3 s (billed; a rotating residential IP doing 8 requests is not a throttle
   shape), local 4-11 s (free, and it is the home IP the flight run depends on).
   `mode` is re-read every iteration so a mid-run `to_local()` widens the gap
   immediately. **Measured caution:** tightening the remote gap was predicted to
   take a run to ~2.0 min and did NOT — the ~10 s saved sits inside Google's
   page-load variance (2.25 then 2.32 measured). Directionally right, not
   decisive; do not re-assert a cost saving here without new numbers.
6f. **Start time is jittered 0-35 min LATER than 05:00, never earlier**
   (`run_hotel_rates.sh`). Earlier would walk back into the 04:00 flight slot
   and its git push. It is applied EVERY night, not only on local-Chrome
   nights, because jittering only those would make the jitter itself the tell.
   The sleep runs BEFORE the `pgrep run_daily.py` stand-down so a slow flight
   run gets extra time to finish rather than costing us the night.
6c. **Local Chrome is the fallback, and it must cover BOTH failure shapes.** A
   MISSING key was handled from day one; an EXHAUSTED key was not, and that gap
   cost five silent nights (see the 2026-08-11 postmortem below). Quota is now
   checked before the session opens, and `to_local()` demotes mid-run if the
   402 arrives between properties — which is exactly how it failed, at property
   7 of 8. Falling back spends the home IP, so it prints loudly when it happens;
   that is the intended trade, because publishing nothing is worse.
7. **Own browser identity**: `BROWSE_SESSION=hotels` (carmax uses `carmax`),
   set before `scraper` is imported, so hotel and flight runs can never share
   or wedge each other's session.
7b. **NEVER run this job concurrently with the flight run, and never move it to
   00:00.** The browsers genuinely do not care — `BROWSE_SESSION` gives each an
   isolated daemon on its own port, and `browse stop --force` is session-scoped
   (all verified 2026-08-16). **Git is what breaks.** The two jobs share ONE
   working tree, and two things were reproduced that day: concurrent
   `add`/`commit` dies on `.git/index.lock` (79 of 80 in a stress loop, and
   only `push` has retry logic here), and — the dangerous one — a `git commit`
   from one job SILENTLY sweeps up the other's staged file, so `data.json` gets
   committed under "Hotel rates refreshed (8/8 live)" and the flight run's own
   `diff --cached --quiet` then reports nothing to publish. No error either
   time. The `pgrep -f run_daily.py` stand-down in `run_hotel_rates.sh` is what
   prevents this; removing it would also mean the job never runs at all at
   00:00, since the flight run is always active then — silently, with exit 0.
8. **Own job, own file, own slot** (`com.jalal.dhaka-hotels`, 5:00 AM): eight
   hotel searches would push the flight run past its 25-min budget and into
   the 35-min overrun guard. It writes only `hotel_rates.json` (never
   data.json, so no race with publish.py), pulls --rebase before pushing, and
   stands down entirely if a flight run is still active. Delays between
   properties are jittered (4–11 s), not a fixed cadence.
9. A run that returns 0 live rates Telegrams once and leaves the table
   honestly stale rather than guessing. **The alert states the reason it
   actually observed** — it must never hardcode a cause. It did until
   2026-08-16 ("Google likely throttling", sent whatever had happened), and
   that one sentence is the entire reason the outage below ran for five days.
   An infra failure carries the `browser backend: ` prefix
   (`hotel_rates.is_infra_note`) so the runner and the alert can tell "our
   browser never started" apart from "Google refused us".

**📉 Postmortem — the five silent nights (2026-08-11 → 08-16).** Browserbase's
free 60 min/month ran out mid-run on 08-11 (6/8 that night, 0/8 for the next
five). Every `browse` command returned `402 Free plan browser minutes limit
reached`; `scraper._run()` printed that sentence to cron.log and returned `""`;
`parse_rate(None)` mapped the empty result to "no page payload (throttled,
blocked or still loading)"; and the 0-rate alert then hardcoded "Google likely
throttling". Four layers, each individually reasonable, that together converted
a precise machine-readable error into a confident wrong diagnosis. **The
scraper.py header already warned about this exact shape** ("2026-07-15: the
browse daemon wedged mid-run … the Telegram alert wrongly blamed Google") — the
lesson was written down and then re-learned on a different substrate. What
changed: `DIAG["last_stderr"]` keeps the CLI's own words; `classify_stderr()`
promotes them to the note; infra failures skip the pointless retry; quota is
checked up front; and fleet-health now grades the oldest ROW stamp instead of
the file's `updated` field, which was green the entire time (see
github-notion-sync AGENTS.md). **Rule of thumb this repo keeps failing on:
never let a diagnosis be more confident than the evidence that produced it —
if the layer below said why, carry the sentence up.**

**🏨 Hotel integration (`hotels.py`, 2026-08-01 evening):** the Marriott
award stay rides with the trip — payload `hotel` (Bangkok: The Athenee,
Luxury Collection; quality bar = "top notch … we did the kempinsky last
time") and `bali.hotel` (The Laguna, the old plan). Stay DATES are derived
nightly from the winning trip's shape (order-aware); POINTS figures are
CURATED live-checked references with a CHECKED date, like baggage.py — NOT
scraped (marriott.com is bot-guarded and dynamic; nightly scraping would
blow the cap). A ≠5-night pairing gets a loud 5th-night-free warning.
Refresh the numbers by re-running the hotel sweep, then bump CHECKED.

**💸 Budget companion (`combo.budget_trip`, 2026-07-27):** alongside the main
trip, the cheapest version of the SAME trip — same Ticket ① (and therefore the
same ORDER), same 5-night Bangkok block — with the Singapore-nights band
waived entirely (≥1 night) and the Dhaka departure free to shift (Jan 27–28
early-exit dates restored under the 30-search allowance). Only shown when
STRICTLY cheaper than the main trip
(else `budget` is None and nothing renders); carries `savings` + human `diffs`
vs main. Surfaces as a 💸 block in Telegram, a collapsible card on the site,
`budget_total` in history/data.json, and the Sheet History column "💸 Budget $"
(appended, per the append-only rule).

**🛏️ Stay math (`stay_value.py`, 2026-08-19):** the SIN night count (2-4
band) is picked ALL-IN — flights + the bold SIN hotel's net out-of-pocket
(rate ×1.12 tax − credits: $400/stay FHR or $350 Edit + $60/day, floored at
0) — with each extra night valued at `EXTRA_NIGHT_WORTH = 225` (Jalal
2026-08-19, derived from his own ≥70% book-now band / Athenee points-value /
replacement cost) and a `DEAD_BAND = 25` incumbent bonus against nightly
flapping (incumbent = last history entry's sg_nights, passed EXPLICITLY to
verify — payload history dedupes same-day entries and cannot reproduce it).
Implemented as an optional `hotel_cost` hook on `combo.order_trip`/
`main_trip` (hookless callers behave exactly as before; `total` stays
FLIGHTS-ONLY everywhere — history, chart, buy-signal). Mode ladder:
**steering** (bold rate ≤3 days old) / **advisory** (stale — table renders,
pick stays flight-only; the hotel job has gone 5 nights dark before) /
**off** (no data; malformed rates also degrade to off — never raise, the
2026-08-19 review's `_rows()` hardening). The block rides as
`payload["stay_value"]`, history gains `sg_allin` + `stay_mode` (the
"(hotel-aware pick)" changes tag fires ONLY on stay_mode="steering"),
Telegram a 🛏️ line, the site a #/stays card + a Tonight chip, the Sheet an
appended "🛏️ SIN all-in" column. A >$50/night cheaper non-bold SIN hotel
triggers a re-bold watchdog note. verify.py re-derives the pick with its OWN
duplicated constants (keep them in sync deliberately — second implementation
is the point). Knobs live at the top of stay_value.py like alerts.BUY_BELOW.
Spec: `docs/superpowers/specs/2026-08-19-hotel-aware-sin-nights-design.md`.

**Hard rules:** 5 Bangkok nights, 2 Istanbul nights, **Singapore 2–4 nights
(a FLEX BAND, not a fixed number)** — `MIN_SG_NIGHTS`/`MAX_SG_NIGHTS`; Jalal
2026-07-27 "minimum of 2 nights" (an overnight first hop had priced a 1-night
ticket below every 2-night option and headlined the trip) + 2026-08-01 "isn't
a hardline. you can take it up to 3 or even 4 if its cheaper in terms of the
flight". An in-band middle always outranks one outside the band, price
decides within it, and an out-of-band day survives only as a flagged
fallback; 3-4 SIN nights are a normal outcome, NOT a sanity warning —
home ≤ Feb 7,
Dhaka ≤ 29 days. **Across orders, a valid trip always outranks a flagged one**
(sort key `(not valid, total)`), so a cheap-but-off-shape order never silently
displaces the on-shape one. Other nights that come out different still win on
price — they're surfaced as a self-check note, never silently. **Airline
rules:** NOTHING excluded — "US-Bangla prices are unbeatable" — the CHEAPEST
wins. THAI / Singapore Airlines are a soft preference: when the winner isn't
THAI/SQ but such an option exists, its upgrade price surfaces as `alt_note`.
`_is_preferred` requires EVERY carrier in a multi-airline string to be THAI/SQ
(substring matching once paid +$1,328 for a half-Malaysia-Airlines ticket;
"Thai Lion Air"/"Thai AirAsia"/"Thai Vietjet" are NOT THAI).

**RETIRED 2026-07-25 — do not resurrect without asking.** The direct open-jaw, the
three-one-ways combo, the Istanbul-only and Singapore-only variants, and the TK
30h-stopover trip are no longer scraped, tracked, charted or Telegrammed
("i only need the main trip … not the others"). **RETIRED 2026-08-01:** every
DPS/Bali search and path — `ISTANBUL2_SEARCH` (the DPS-return Ticket ①),
`BALI_LEGS`, `SG_TICKET_SEARCHES`, `scrape_sg_ticket`, and the Bali-era combo
pair `main_trip_bali`/`budget_trip_bali`. All retired configs
(`OPENJAW_SEARCHES`, `STOPOVER_SEARCH`, `ISTANBUL3_SEARCH`, the Bali set) and
their combo functions (`best_structures`, `best_combos`, `best_singapore`,
`cheapest_by_leg`) still work and are still tested — re-adding one is a
two-line change in `scrape_tickets_all()` / `LEGS`. Their historical numbers
stay in `site/data.json` and in the Sheet's columns; nothing is rewritten
backwards. Specs: `docs/superpowers/specs/2026-07-18-singapore-detour-variant-design.md`
(the trip's evolution), `2026-08-01-bangkok-singapore-swap-design.md` (the swap).

Redesigned 2026-07-15 from the original round-trip BOS⇄DAC/BKK watcher; design spec:
`docs/superpowers/specs/2026-07-15-three-leg-trip-redesign-design.md`.

## 2. Architecture / data flow

```
launchd 12:00am + 2:00am retry slot (com.jalal.dhaka-flights.plist, parallel with com.jalal.carmax — isolated browse sessions; retry no-ops after success via .last_run_date; run_daily.sh Telegrams on a crash exit AND refuses to START after 5:30 AM — user awake/working — so wake-replays of missed slots skip for the day) → run_daily.sh → run_daily.py
  scraper.py   scrape_tickets_all()    Ticket ① — 2 multi-city searches (one per
                                       order: …+ SIN→BOS and …+ BKK→BOS Feb 6),
                                       up to TICKET1_ATTEMPTS=3 tries each
                                       (nothing else can substitute, so they run
                                       FIRST and retry hardest), no airline filter
               scrape_sg_tickets_all() Ticket ② as one ticket — 7 multi-city
                                       searches (TICKET2_SEARCHES, order-tagged:
                                       4 DAC→SIN→BKK + 3 DAC→BKK→SIN, incl. the
                                       Jan 28 4-SIN-night flex pairs; SEPARATE
                                       list; the open-jaw pairing loop would
                                       mis-handle them)
               scrape_all()            Ticket ② as two one-ways — 18 searches
                                       (LEGS: DAC→SIN + DAC→BKK Jan 27–Feb 1,
                                       SIN→BKK Jan 31–Feb 2, BKK→SIN Feb 2–4)
               scrape_bali_watch()     🌴 benchmark, runs LAST — 3 searches
        │  drives real Chrome via the `browse` CLI (a11y-tree snapshots)
        ▼
  combo.py     ORDERS             the two city orders: route pair + Ticket ①
                                   ret_city + which city holds the 5-night block
               order_trip()        best complete trip for ONE order
               main_trip()         cheaper valid order wins; loser rides along as
                                   `other_order` (slim dict + Δ) — never hidden
               ticket1_options()   same-dates-AND-same-return alternatives to ①
               ticket2_options()   same-dates alternatives to ②, within the
                                   winning order ('1 ticket'/'2 tickets', deduped)
               best_structures/best_combos/best_singapore/cheapest_by_leg/
               main_trip_bali/budget_trip_bali — retired from the nightly path,
                                   kept working + tested
  baggage.py   annotate()/warnings()  per-leg allowance from a sourced carrier
                                   table (Google's tree has NO bag data); US piece
                                   rule for Ticket ①, Asian weight rules for ②
        ▼
  sheet_writer.py → Google Sheet tab "Google Flights" (Ticket ① + ② fares then the
                    one-way legs, replaced daily) + "History" tab (append-only)
  notify_telegram.py → Telegram: the trip, per-leg baggage, same-date alternatives
  publish.py  → site/data.json (main + options + appended history) → git commit+push
        ▼
  site/index.html (static, deployed once on Vercel) fetches data.json raw from
  GitHub on every page load — no redeploy needed for data updates. Hash-routed
  boarding-pass dashboard (redesigned 2026-08-02, rollback tag v1-pre-overhaul),
  four routes in one file:
  #/ Tonight (verdict pass: order-aware mono route · total + Δ vs yesterday ·
  buy-signal/price-context chips · ①/② stub row · sparkline · 4 drill-in tiles) ·
  #/flights (Ticket ① and ② as passes with per-leg 🧳 lines · budget card ·
  other-order card · alternatives with Δ-vs-chosen · baggage table · playbook ·
  all one-way fares) · #/stays (Athenee pass · Bali hotel footnote · IST/SIN
  card-play offset tables · hotel playbook) · #/history (4-series chart · trend
  summary · sortable night table w/ tap-row detail · Bali watch card).
  Can never render blank: fetch falls back raw→local→localStorage last-good
  (labeled banner) →designed error screen; every section renders through a
  renderSafe error boundary; client-side validatePayload + arithmetic checks
  feed the collapsed 🧪 footer.
```

## 3. How to run / test / deploy

- Tests: `python3 -m pytest tests/ -q` (pure logic only — parsers, combos,
  baggage table, sheets rows; no browser).
- Manual full run: `./run_daily.sh` (delete `.last_run_date` first or it skips).
- One search interactively: `python3 -c "from scraper import scrape_route; print(scrape_route('DAC','SIN','January 30, 2027'))"`.
- Dashboard deploy (only when site/index.html changes): `cd site && vercel --prod --yes`
  (project `dhaka-flights`, account `jalalchowdhury-8053`). Data updates need NO deploy.
- **Rollback the site to the pre-overhaul version** (tagged `v1-pre-overhaul`,
  2026-08-02): `git checkout v1-pre-overhaul -- site/index.html && git commit
  -m "Rollback site to v1" && git push && cd site && vercel --prod --yes`.
  Plan B: Vercel dashboard → Deployments → pick an older one → Promote to
  Production.

## 4. Secrets & env

- `.env` in repo root (gitignored): `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`.
- Google service account JSON: `~/.config/mcp-google-sheets/service-account.json`.
- git push uses the Mac's stored GitHub credentials; Vercel CLI is logged in locally.

## 4b. Redundancy layers (hardened 2026-07-18 for the 6-week decision window)

Jalal relies on this nightly until an early-September 2026 booking decision
(calendar reminder set for Sep 1). Defense in depth:
1. **Wake**: `com.jalal.keepawake` LaunchAgent runs `caffeinate -s` with
   KeepAlive+RunAtLoad — survives reboots/terminal closes (the old ad-hoc
   terminal caffeinate died with its window). pmset would otherwise sleep.
2. **Slots**: launchd fires 12:00 + 2:00 + 4:00; `.last_run_date` stamp makes
   later slots no-ops after success. Stamp is written ONLY if ≥1 trip structure
   was built — a catastrophic zero-structure day auto-retries.
3. **No-start-after-5:30** window guard (wake-replays skip, user is working).
   3b. **Same-day rescrape caution (2026-08-01):** after ~100 searches in one
   afternoon every browse command crawled to 30s+ timeouts on FOUR straight
   manual attempts even with a clean process table — consistent with Google
   slow-walking the IP. Repeated same-day manual runs are the one thing that
   degrades this scraper; prefer the midnight window and its 2:00/4:00 slots.
   Also: killed manual runs leave ORPHANED browse daemons + stagehand Chrome
   instances that compound the slowness — `pkill -f "browse --session";
   pkill -f stagehand` before relaunching (safe when no other scraper is
   mid-run; carmax runs at midnight).
4. **Alerts**: wrapper Telegrams on crash exit; in-run Telegram warns on
   0-flight days (browser-broken vs Google-empty distinguished via DIAG).
5. **History in triplicate**: site/data.json (append-only, keyed by date) +
   its full git history on GitHub (pushed nightly) + the Google Sheet
   "History" tab (one appended row/day, `sheet_writer.append_history_row`).
   Plus `backups/` keeps the last 60 daily local snapshots (gitignored;
   Time Machine → T7 covers the disk).
6. **Staleness tripwire**: the dashboard shows a red banner when data.json is
   >36 h old — a silently dead tracker is visible on first glance.
7. Self-check warnings on the site are COLLAPSED by default (tap to expand).

## 4c. Baggage (added 2026-07-25)

Google Flights' a11y tree carries **no** bag information, and the real allowance
depends on the fare brand (EcoFly / Economy Lite / Basic) which only appears at
the airline's checkout. So `baggage.py` is a **sourced lookup table**, not a
scrape: every carrier entry has an official `url` and a `confidence`
(`verified` = read off the airline's own page on `CHECKED`, `typical`, `varies`,
`unknown`). Rules:

- **Never** present these numbers as the booked allowance — the UI says
  "reference — the checkout page is the authority", keep it that way.
- Ticket ① is priced under the **US piece concept** (any itinerary touching the
  Americas, both directions, whole through-ticket): Turkish/Gulf 2 × 23 kg,
  European carriers usually 1 × 23 kg. Ticket ② uses **Asian weight rules**,
  which vary by carrier *and* route (US-Bangla: 40 kg DAC→SIN but 30 kg
  DAC→BKK, 20 kg to Doha).
- **CARRIERS key order matters**: `_carrier_key` is first-substring-match in
  insertion order, so "thai lion"/"thai vietjet"/"thai airasia" MUST stay
  ABOVE "thai" — otherwise the Thai LCCs inherit THAI Airways' full-service
  allowance (caught 2026-08-01 while adding the BKK routes).
- A multi-city ticket's **second leg carrier is unknown to us** — Google names
  only the first leg. `annotate()` says "not shown on this ticket" rather than
  guessing; don't "fix" that by assuming the first carrier flies both legs.
- Multi-airline strings ("US-Bangla + Jetstar") get a `summary` naming BOTH
  allowances — the cheap half often includes no free bag at all.
- When a carrier's policy changes, edit `CARRIERS` and bump `CHECKED`.

## 4d. Buy-signal layer (`alerts.py`, added 2026-07-25)

The rule, agreed with Jalal explicitly: **before the book-by date price
decides; after it, the date decides.** Three stages keyed off two knobs at the
top of `alerts.py` (`BUY_BELOW = 4500`, `BOOK_BY = Sep 20 2026`,
`WINDOW_OPENS = Sep 1`). `TRIP_TRACKED_SINCE = 2026-08-01` — the Bangkok-era
epoch; Bali-era totals are a different trip and never pollute rank/low context
(`BUY_BELOW` kept at $4,500 through the swap until real BKK numbers arrive):

- **watch** (→ Sep 1): message stays quiet; a context line always shows rank +
  distance-to-low. Alerts only on 🔥 new all-time low (trip or Ticket ① alone)
  or 🚨 buy zone (≤ $4,500).
- **window** (Sep 1–20): + countdown line; buy-zone hit leads 🚨 BOOK NOW.
- **past** (after Sep 20): every message leads 🚨 book-this-week and the price
  threshold RETIRES — don't re-add it, that's the point.

Also here: `changes_since()` — the diff vs yesterday's entry (ticket airlines,
Ticket ② composition 1-ticket ⇄ 2-one-ways + dates, ≥$50 per-ticket moves,
nights drift) with a 🧳⚠️ suffix when the change alters baggage rules. Rank /
low comparisons only use entries from `TRIP_TRACKED_SINCE` (2026-07-18) — the
earlier open-jaw-era totals are a different trip and must not pollute the low.
Everything lands in the payload (`alerts`, `price_context`, `countdown`,
`changes`) so Telegram and the site render the same facts;
`notify_telegram.build_message(payload)` takes the whole payload for that
reason.

## 5. Gotchas / hard rules

1. **Google shows the TOTAL price for all selected passengers** (verified 2026-07-15:
   1-pax $367 vs 3-pax $1,099). `price_total` = whole family. Never label it per person.
2. **Wedged browse daemon** ⇒ every command times out, then silent `about:blank`
   trees with exit 0 ⇒ fake 0-result runs. Hardening lives in `_run()` (timeout →
   `DIAG`), blank-page bail, per-route retry, 4-dead-routes abort, and the Telegram
   alert distinguishes LOCAL browser failure from a real 0-result day.
   Debug a 0-day via `cron.log` + `debug_last_zero.txt`.
3. Airport pickers must have an AIRPORT_PICK entry — the bare-code fallback substring-matches random tree lines ("IST" hit "listitem") and derails the form. BKK TYPES "Bangkok" (`TYPE_AS`) and picks the `option: Bangkok, Thailand` CITY line — typing the code offers ONLY Suvarnabhumi (live-checked 2026-08-01), which would hide Don-Mueang LCC fares (Thai AirAsia/Lion); the `option:` prefix keeps the keyword off the input box's own value line and off "Bangkok Yai, Thailand". **Multi-city result lines say "From X US dollars total."**; one-way lines say just
   "From X US dollars." — `_parse_results` accepts both. Flight details on the
   multi-city selection page describe the FIRST leg; the price includes its cheapest
   completion. Only ~top-10 fares show inline — the scraper clicks "View more flights".
4. **The trip must NEVER be dropped silently** (2026-07-16: the exact-5-night
   pairing rule hid a valid $3.4k open-jaw from the daily message). When no
   5-night Bangkok pairing exists, 4/6 nights are used and `flag` is set (shown
   verbatim in Telegram + site badges); a day with only <2 Singapore nights is
   likewise kept but flagged; off-target Istanbul nights become a
   self-check note. The parser keeps the CHEAPEST `MAX_RESULTS` fares, not the
   first in page order. `sanity.py` warns loudly when Ticket ① prices but no
   trip builds, and when one ORDER's Ticket ① variant comes back empty (the
   "cheaper order" claim is hollow when only one order priced).
5. **Trip rules live in combo.py** (`MAX_DHAKA_DAYS=29` counting both end days,
   `IDEAL_BKK_NIGHTS=5`, `HOME_DEADLINE=Feb 7`, `ORDERS` for the two city
   orders). Open-jaw "home" date is a +1-day heuristic (return-leg arrival
   isn't parsed on the selection page).
6. **publish.py must never crash the run** — it swallows all exceptions. History is
   append-only inside `site/data.json`, keyed by ISO date (same-day reruns overwrite
   that day's entry).
7. The launchd job often fires twice; `.last_run_date` (written only on success)
   makes the duplicate skip. Machine stays awake via a long-running `caffeinate`.
8. Booking insight (2026-07-15): the open-jaw ticket was ~$1.7k cheaper than
   separate one-ways ($3.4k vs $5.1k for the two long legs). Thailand + Singapore
   are visa-free for US passports; both want an online arrival card ≤3 days out
   (TDAC / SG Arrival Card). The old Indonesia e-VOA onward-proof constraint died
   with Bali.

## 6. Known issues / TODO

- `main_flyai.py` / `scraper_flyai.py` are dead legacy (flyai experiment) — ignore.
- `cron.log`, `debug_last_zero.txt`, `.DS_Store` are untracked local artifacts.
- Ticket ① is fixed to BOS→IST Jan 4 / IST→DAC Jan 7 / {SIN|BKK}→BOS Feb 6.
  Other outbound or return dates would change the trip's shape, so they're a
  product decision, not a config tweak — ask before adding.
- **Killed-run gotcha (2026-07-18):** a full run is ~20-24 min (30 searches
  with one browser session per run, 2026-08-01 evening). Never
  run it inside a harness/tool with a ≤10-min timeout — it gets SIGKILLed
  mid-scrape (no stamp written, no output flushed with buffered stdout). Manual
  runs: `nohup … python3 -u run_daily.py > log 2>&1 &` and watch the log. The
  launchd job has no timeout and is unaffected.

## 7. File map

- `run_daily.sh` / `run_daily.py` — launchd entrypoint; stamp + DIAG alerting;
  arms the ⏱ overrun clock (`scraper.begin_run()`) and folds deadline skips +
  📐 contract findings into the night's warnings
- `schema_check.py` — the data.json contract as code: `validate(payload)`
  returns human-readable violations (never raises, never blocks publishing);
  run nightly from run_daily between the verify block and the sheet write.
  site/index.html's `validatePayload()` mirrors its TOP/numeric lists — keep
  the two in sync when the payload shape changes
- `sanity.py` — self-check watchdog run before every send: Ticket ① must price
  (per order variant too), a priced Ticket ① must produce a trip, every
  leg×date and Ticket ② order+date pair must have fares, yesterday's totals
  must not silently vanish, >25% swings, parser drift, and trip-shape drift
  (2 IST / 2 SIN / 5 BKK nights) all get flagged. Violations ride along to
  Telegram ("🧪 Self-check") and the site's amber banner. When adding a tracked
  search, add its invariant here too.
- `scraper.py` — browse-CLI form driving + parsing (one-way & multi-city); LEGS,
  STOPOVER_SEARCHES (2 Ticket ① variants), TICKET2_SEARCHES + ORDER_ROUTES
  (+ retired configs, kept). ⏱ Overrun guard (2026-08-02): past
  `RUN_DEADLINE_MIN` (35 min from `begin_run()`), `scrape_bali_watch` skips
  entirely and `scrape_all` drops its remaining one-ways — skips land in
  `DIAG["deadline_skips"]`; Ticket ①/② multi-city searches are never skipped.
  Interactive use has no deadline (`begin_run` is opt-in)
- `combo.py` — trip rules, `ORDERS`, `order_trip`, `main_trip`, `budget_trip`,
  `ticket1_options`, `ticket2_options`, `sin_night_flight_totals` (+ retired
  `best_structures` / `best_combos` / `best_singapore` / `cheapest_by_leg` /
  `*_bali`)
- `baggage.py` — sourced per-carrier allowance table; `annotate`, `warnings` (§4c)
- `hotels.py` — curated Marriott award-stay references + `hotel_plan(trip)`
  (order-aware stay dates; points are checked references, never scraped)
- `stay_value.py` — 🛏️ hotel-aware SIN night-count layer (§1 Stay math):
  knobs, mode ladder, the combo hook, the payload block, the re-bold watchdog
- `hotel_rates.py` / `run_hotel_rates.py` / `run_hotel_rates.sh` — the nightly
  IST/SIN public-rate refresh (§1 "Nightly hotel rates"): shortlist config,
  fail-closed date/property guard, offset math, and the 5 AM launchd job that
  writes `site/hotel_rates.json`. A miss keeps the last good rate and its date
- `alerts.py` — buy-signal stages, price context, countdown, change diff (§4d)
- `verify.py` — the nightly 3-perspective independent re-check (keep it
  independent of combo.py; that's the point) + the 🛏️ stay-math
  re-derivation with deliberately duplicated constants
- `publish.py` — `build_today` → payload → `write_payload` (backup, atomic
  write, push). git push retries 3× (10s/30s backoff) then warns Telegram via
  `_telegram_warn` — a failed push can no longer leave the site silently stale
- `sheet_writer.py`, `notify_telegram.py` — outputs
- `site/` — static dashboard (index.html) + data.json (machine-written).
  REBUILT 2026-08-02 as a hash-routed boarding-pass app (design-taste +
  dataviz skills; rollback tag `v1-pre-overhaul`). Conventions:
  - Boarding-pass tokens: warm-paper light is home, dark is a navy night
    variant (never grey inversion); `--ink-3` is #67624f, darkened from the
    spec's #8a8371 to pass WCAG AA — don't lighten it back. Theme toggle
    cycles auto→dark→light via `data-theme` on :root; the two explicit
    `[data-theme]` blocks must keep beating the media query in BOTH
    directions.
  - Robustness: `loadData()` falls back GitHub-raw → same-origin copy →
    localStorage last-good (banner) → designed error screen; every section
    renders through `renderSafe()`; `validatePayload()` MIRRORS
    schema_check.py's TOP/numeric lists — change one, change the other;
    `arithmeticFindings()` re-checks ①+②=total + the history mirror.
    Findings join the payload's own warnings in the collapsed 🧪 footer.
  - `?qa=<name>` dev hook: serves `./qa/<name>.json` instead of live data
    (build mutants with jq, delete the folder after — never commit qa/).
  - Chart: 4 validated categorical slots, assignment order trip/Bali/①/②
    IS the CVD-safety mechanism — don't reshuffle; series colors were
    re-validated with the dataviz checker on the 2026-08-02 surfaces (light
    #2a5da8/#c0562e/#178f6b/#a87b00, dark #5a91e8/#d96536/#27a37b/#bb8626);
    2px lines, ring endpoints, hairline grid, $ ticks, legend, selective
    end labels, crosshair tooltip via bindChartHover.
  - `orderInfo()` maps every trip shape incl. `bali-rev`; keep it in sync
    with combo.ORDERS when orders change.
- `main.py` — manual run: scrape + sheet + terminal summary (no Telegram/publish)
- `tests/` — pytest suite (291 tests; `test_main_trip.py` holds the shared trip
  fixtures, `test_baggage.py` guards the allowance table's honesty)

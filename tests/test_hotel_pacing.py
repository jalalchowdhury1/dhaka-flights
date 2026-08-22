"""Quota pacing for the nightly hotel refresh.

Demand (~30 nights x EST_RUN_MINUTES — ~5.7 billed min at 19 properties since
2026-08-22, ~2.3 at the original 8) exceeds Browserbase's 60-min free month,
so some nights each month must run on local Chrome. WHICH nights
is the thing that matters: letting the quota run dry puts them all in one
consecutive block at month-end, and a multi-night burst of hotel searches from
the home IP is the shape that got slow-walked on 2026-08-03. A single isolated
night is not.

These tests pin the two properties that make that true — it spends the month's
quota rather than hoarding or blowing it, and the local nights land scattered
— because a pacing bug is SILENT: the rates still publish either way.
"""
import calendar
import datetime
import random
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run_hotel_rates as rh

CAP = rh.FREE_TIER_MINUTES


class Seeded:
    """Deterministic stand-in for the random module."""
    def __init__(self, seed): self._r = random.Random(seed)
    def random(self): return self._r.random()


def simulate(year, month, cap=CAP, cost=None, seed=7):
    """Run a whole month and report which nights fell back to local Chrome."""
    cost = cost if cost is not None else rh.EST_RUN_MINUTES
    rng, used, local_nights = Seeded(seed), 0.0, []
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        today = datetime.date(year, month, day)
        if used >= cap or rh.should_conserve(used, cap, today=today, rng=rng):
            local_nights.append(day)     # local Chrome: spends no quota
        else:
            used += cost
    return local_nights, used


def test_unknown_quota_does_not_conserve():
    """A failed usage lookup must not silently push every night onto the home
    IP — the 402 fallback is the real backstop for that."""
    assert rh.should_conserve(None, CAP) is False
    assert rh.should_conserve(10, None) is False


def test_exhausted_quota_always_conserves():
    assert rh.should_conserve(CAP, CAP) is True
    assert rh.should_conserve(CAP + 5, CAP) is True


def test_cannot_afford_one_more_run_conserves():
    """Less than one run's worth left: spending it half-way is worse than not
    starting, because a session killed mid-run still bills."""
    assert rh.should_conserve(CAP - (rh.EST_RUN_MINUTES / 2), CAP) is True


def _expected_local(year, month, cost=None):
    """Nights that CANNOT be remote at this run cost: demand − cap, in runs."""
    cost = cost if cost is not None else rh.EST_RUN_MINUTES
    days = calendar.monthrange(year, month)[1]
    return max(0, days - int(CAP // cost))


def test_day_one_conserve_rate_tracks_the_shortfall():
    """Day 1 with a full tank conserves with probability shortfall/nights —
    ~13% when 8 properties fit the cap, ~68% at 20 properties. Pin the
    FORMULA, not a seed: asserting 'mostly remote' was true only while
    demand barely exceeded the cap."""
    d = datetime.date(2026, 9, 1)
    nights = 30
    need = nights * rh.EST_RUN_MINUTES
    p = max(0.0, (need - CAP) / rh.EST_RUN_MINUTES) / nights
    trials = 200
    local = sum(rh.should_conserve(0, CAP, today=d, rng=Seeded(s))
                for s in range(trials))
    sd = (trials * p * (1 - p)) ** 0.5
    assert abs(local - trials * p) <= 4 * sd + 1, \
        f"day-1 conserve rate {local}/{trials} vs expected p={p:.2f}"


def test_pacing_bites_harder_as_the_quota_runs_down():
    """The mirror of the above, stated as the property that actually matters:
    conserving must become MORE likely as the tank empties. (With 4 min left
    over 3 nights you can afford ~1.7 remote nights, so ~43% is the correct
    rate there — not a majority. Asserting >50% was my arithmetic error, and
    an absolute threshold would have been a magic number either way.)"""
    def rate(day, used):
        d = datetime.date(2026, 9, day)
        return sum(rh.should_conserve(used, CAP, today=d, rng=Seeded(s))
                   for s in range(50))

    early, late = rate(1, 0), rate(28, CAP - 4)
    assert late > early, f"pacing did not tighten: early={early} late={late}"
    assert late >= 15, f"pacing barely bites near the end: {late}/50"


def test_a_month_never_runs_dry():
    """The whole point: quota must still be available on the last night."""
    for (y, m) in ((2026, 9), (2026, 10), (2027, 2)):
        _, used = simulate(y, m)
        assert used <= CAP, f"{y}-{m} overspent: {used:.1f} > {CAP}"


def test_local_nights_match_demand_and_are_not_all_at_month_end():
    """Whatever the shortlist length, the month must (a) spend the quota
    rather than hoard it, (b) go local only about as often as demand
    forces, and (c) scatter those nights instead of clumping at the end —
    a multi-night burst from the home IP is the shape Google slow-walked."""
    local, used = simulate(2026, 10)          # 31 days
    want = _expected_local(2026, 10)
    assert want - 3 <= len(local) <= want + 4, \
        f"local nights {len(local)} vs demand-forced {want}: {local}"
    assert used > CAP * 0.75, f"hoarded quota instead of spending it: {used:.1f}"
    tail = set(range(31 - len(local) + 1, 32))
    assert set(local) != tail, f"local nights clumped at month-end: {local}"


def test_scattering_holds_across_seeds():
    """Not an artifact of one lucky seed."""
    clumped = 0
    for seed in range(20):
        local, _ = simulate(2026, 10, seed=seed)
        if not local:
            continue
        tail = set(range(31 - len(local) + 1, 32))
        if set(local) == tail:
            clumped += 1
    assert clumped == 0, f"{clumped}/20 seeds produced a month-end clump"


def test_a_cheaper_run_needs_fewer_local_nights():
    """Directional only. A cheaper run must never need MORE local nights.

    Deliberately not asserting a specific saving: the mode-aware jitter was
    predicted to take a run 2.25 -> 2.0 min and measurement said otherwise
    (2.25 and 2.32 observed), so pinning a number here would encode a guess."""
    local_expensive, _ = simulate(2026, 9, cost=2.6)
    local_cheap, _ = simulate(2026, 9, cost=2.0)
    assert len(local_cheap) <= len(local_expensive)


def test_pacing_survives_a_run_costing_more_than_estimated():
    """EST_RUN_MINUTES is a measured guess and reality will drift above it.
    When it does, pacing must still not overspend — the hard 402 fallback is
    the backstop, but it should not be reached in an ordinary month."""
    for real_cost in (rh.EST_RUN_MINUTES, rh.EST_RUN_MINUTES + 0.3):
        _, used = simulate(2026, 10, cost=real_cost)
        assert used <= CAP, f"overspent at {real_cost} min/run: {used:.1f}"


def test_jitter_is_wider_on_local_than_on_remote():
    """Seconds are billed on remote and free on local, and it is local that
    touches the home IP — so the spacing must not be one number."""
    assert rh.JITTER["local"][0] > rh.JITTER["remote"][1], \
        "local spacing must be strictly wider than remote"
    assert rh.JITTER["remote"][0] >= 1, "never a zero-gap burst"


def test_every_mode_the_runner_can_report_has_a_jitter_band():
    """to_local()/start_session() return these strings; a missing key would
    raise mid-run, after the quota had already been spent."""
    assert set(rh.JITTER) >= {"remote", "local"}


def test_run_estimate_scales_with_the_shortlist():
    import hotel_rates
    assert rh.EST_RUN_MINUTES == round(
        rh.PER_PROPERTY_MINUTES * len(hotel_rates.SHORTLIST), 1)
    assert rh.PER_PROPERTY_MINUTES >= 0.29          # the 2026-08-16 measurement


def test_local_spacing_is_wide_enough_for_twenty_searches():
    """20 searches from the home IP must not look like the 2026-08-03 burst
    (~10 rapid searches). ≥8 s floor, on top of the page polling."""
    assert rh.JITTER["local"][0] >= 8

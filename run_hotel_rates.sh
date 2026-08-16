#!/bin/bash
# Wrapper for launchd — same environment setup as run_daily.sh.
#
# Runs at 5:00 AM, deliberately AFTER every flight slot (0:00 / 2:00 / 4:00) so
# the two jobs never scrape at the same time (Google throttles a busy IP — see
# AGENTS.md §4b.3b) and never race on a git push.

source /Users/jalalchowdhury/.bash_profile 2>/dev/null || true
source /Users/jalalchowdhury/.zshrc 2>/dev/null || true

export HOME=/Users/jalalchowdhury
export USER=jalalchowdhury
export DISPLAY=:0
export PATH="/Users/jalalchowdhury/.nvm/versions/node/v24.15.0/bin:/usr/local/bin:/opt/homebrew/bin:/Library/Developer/CommandLineTools/usr/bin:$PATH"

cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"

# Own browser identity so hotel traffic never shares a session with the flight
# run, and the Browserbase key so scraping leaves from their residential IPs
# rather than this house's (see AGENTS.md §1 "Nightly hotel rates").
export BROWSE_SESSION=hotels
set -a; [ -f .env ] && . ./.env; set +a

# Jitter the start 0-35 min LATER — never earlier. 5:00 AM already sits after
# every flight slot (0:00/2:00/4:00) and after the 35-min overrun guard; drifting
# earlier would walk straight back into the flight run and its git push.
# Applied EVERY night, not only on the nights that fall back to local Chrome:
# jittering only the local nights would make the jitter itself the tell. Sleeping
# before the stand-down check below is deliberate — it gives a slow flight run
# extra time to finish instead of costing us the night.
JITTER_SECONDS=$(( RANDOM % 2101 ))
echo "$(date): jittering start by ${JITTER_SECONDS}s"
sleep "$JITTER_SECONDS"

# If a flight run is still going (a slow night), stand down rather than fight it
# for the browser session — tomorrow's rates are worth less than tonight's fares.
# This is also what keeps the two jobs off each other's git index: they share one
# working tree, and a concurrent add/commit either dies on index.lock or silently
# sweeps the other job's staged file into the wrong commit (both reproduced
# 2026-08-16). Never remove this guard without giving them separate checkouts.
if pgrep -f "run_daily.py" > /dev/null; then
  echo "$(date): flight run still active — skipping hotel refresh today"
  exit 0
fi

echo "===== $(date) hotel rate refresh ====="
python3 -u run_hotel_rates.py
echo "===== $(date) done (exit $?) ====="

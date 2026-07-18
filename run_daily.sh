#!/bin/bash
# Wrapper for launchd — sets up the user environment that GUI apps need

# Load user environment (PATH, HOME, display)
source /Users/jalalchowdhury/.bash_profile 2>/dev/null || true
source /Users/jalalchowdhury/.zshrc 2>/dev/null || true

export HOME=/Users/jalalchowdhury
export USER=jalalchowdhury
export DISPLAY=:0

# Make sure node/npm/browse are on PATH
export PATH="/Users/jalalchowdhury/.nvm/versions/node/v24.15.0/bin:/usr/local/bin:/opt/homebrew/bin:/Library/Developer/CommandLineTools/usr/bin:$PATH"

cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"

# Policy: never START a run after 5:30 AM — Jalal is awake and working. Catches
# launchd wake-replays of a missed midnight/2:00 slot, which would otherwise
# fire the moment the Mac wakes and land mid-workday. (run_daily.py's own
# .last_run_date stamp already prevents a duplicate once one run has succeeded.)
h=$(date +%-H); m=$(date +%-M)
if [ "$h" -gt 5 ] || { [ "$h" -eq 5 ] && [ "$m" -ge 30 ]; }; then
    echo "=== $(date '+%F %H:%M') past 5:30 AM — skipping (wake-replay of a missed slot) ==="
    exit 0
fi

/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3 run_daily.py
rc=$?
if [ $rc -ne 0 ]; then
    # A hard crash (exception) is otherwise silent — the in-script Telegram
    # warnings only cover zero-flight runs. Same pattern as carmax-scraper.
    set -a; source .env 2>/dev/null; set +a
    [ -n "$TELEGRAM_TOKEN" ] && curl -fsS -m 15 "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        --data-urlencode chat_id="${TELEGRAM_CHAT_ID}" \
        --data-urlencode text="⚠️ Dhaka flights run CRASHED (exit $rc) at $(date '+%H:%M'). See cron.log. Auto-retries at 2:00 AM if before then." \
        >/dev/null 2>&1 || true
fi
exit $rc

#!/bin/bash
# bench-runner.sh — runs live benches OUTSIDE DeepSeek's sandbox on its behalf.
#
# Why: a `browse` daemon started from inside ~/.dsh/wall.sb cannot launch
# Chrome (wsUrl stays null) and then wedges every caller for 30 s — proven
# 2026-09-18 09:40. scraper._ensure_session restarts the daemon at the start
# of every run, so NO live scrape can ever run from inside the sandbox.
#
# Protocol (DeepSeek side):
#   1. write ONE line into bench/queue/<name>.req, e.g.
#        bench.py --engine legacy --set smoke
#        profile_legacy.py
#   2. poll until bench/queue/<name>.done exists (bench/queue/<name>.log has
#      the full stdout+stderr, and bench/*.json is written by bench.py itself)
#   3. never write a second .req while one is pending; never touch the daemon.
#
# Runner side: `tmux new -d -s jev-bench "bash bench-runner.sh"` from a normal
# (unsandboxed) shell. Only whitelisted scripts/args are ever executed.

cd "$(dirname "$0")" || exit 1
PY=/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3
export PATH="/Users/jalalchowdhury/.nvm/versions/node/v24.15.0/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p bench/queue
echo "bench-runner up $(date '+%F %T') in $(pwd)"

ALLOWED='^(bench\.py( --engine (legacy|jev))?( --set (smoke|full))?( --repeat [1-5])?( --no-key)?|profile_legacy\.py)$'

while true; do
  for req in bench/queue/*.req; do
    [ -e "$req" ] || continue
    name="${req%.req}"
    line="$(head -1 "$req" | tr -d '\r')"
    mv "$req" "$name.running"
    {
      echo "=== $(date '+%F %T') request: $line"
      if [[ "$line" =~ $ALLOWED ]]; then
        now=$(( 10#$(date +%H) * 60 + 10#$(date +%M) ))   # minutes since midnight
        if [ "$now" -lt 450 ] || [ "$now" -ge 1410 ]; then   # before 07:30 or from 23:30
          echo "REFUSED: outside the 07:30-23:30 window"
        else
          # shellcheck disable=SC2086
          "$PY" $line
          echo "=== exit $?"
        fi
      else
        echo "REFUSED: not on the whitelist: $line"
      fi
      echo "=== $(date '+%F %T') end"
    } > "$name.log" 2>&1
    mv "$name.running" "$name.done"
  done
  sleep 5
done

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

/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3 run_daily.py

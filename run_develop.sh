#!/usr/bin/env bash
# Local / server scheduler for DEVELOP branch — runs separately from main.
# Usage:
#   ./run_develop.sh            # single dry-run using develop code
#   ./run_develop.sh --live     # live post with DEVELOP creds
#   ./run_develop.sh --loop     # simple daily loop (for a VPS, use cron instead)
set -euo pipefail
cd "$(dirname "$0")"

BRANCH="main"
echo "== fetching $BRANCH =="
git fetch origin "$BRANCH" >/dev/null 2>&1 || true
git worktree list | grep -q "wt-develop" || git worktree add ./wt-develop origin/$BRANCH 2>/dev/null || git worktree add ./wt-develop $BRANCH 2>/dev/null || true
cd ./wt-develop 2>/dev/null || true
git checkout $BRANCH 2>/dev/null || true
git pull origin $BRANCH 2>/dev/null || true

export TZ="Asia/Kolkata"
export DRY_RUN="true"
if [[ "${1:-}" == "--live" ]]; then
  export DRY_RUN="false"
  # expects IG_USER_ID_DEVELOP / IG_ACCESS_TOKEN_DEVELOP in env; map to names auto_post.py reads
  export IG_USER_ID="${IG_USER_ID_DEVELOP:-$IG_USER_ID}"
  export IG_ACCESS_TOKEN="${IG_ACCESS_TOKEN_DEVELOP:-$IG_ACCESS_TOKEN}"
fi

pip install -q -r requirements.txt
python3 auto_post.py --verify-365 "$(date +%Y)"
python3 auto_post.py

if [[ "${1:-}" == "--loop" ]]; then
  echo "entering daily loop (Ctrl+C to stop)..."
  while true; do sleep 86400; python3 auto_post.py; done
fi

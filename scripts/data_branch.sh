#!/usr/bin/env bash
# Keeps drafts, state and images on a separate "data" branch.
# The branch is squashed to a single commit every time, so the repo never grows.
#   data_branch.sh pull          -> clone/initialise ./data
#   data_branch.sh push "msg"    -> commit + force-push ./data
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_URL="${DATA_REPO_URL:-https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git}"

case "${1:-}" in
  pull)
    rm -rf data
    if git ls-remote --exit-code --heads "$REPO_URL" data >/dev/null 2>&1; then
      git clone -q --depth 1 --branch data "$REPO_URL" data
    else
      mkdir -p data/media && cd data && git init -q -b data && git remote add origin "$REPO_URL"
      echo '# Bot data (drafts, images, state) - managed automatically, do not edit' > README.md
    fi
    ;;
  push)
    cd data
    git checkout -q --orphan "snap-$(date +%s%N)"
    git add -A
    git -c user.name="revert-bot" -c user.email="revert-bot@users.noreply.github.com" \
        commit -q -m "${2:-update}" || exit 0
    git push -q -f origin HEAD:data
    ;;
  *) echo "usage: $0 pull|push [message]"; exit 1 ;;
esac

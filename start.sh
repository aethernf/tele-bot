#!/usr/bin/env bash
# Start script untuk Railway: clone repo keylist kalau belum ada, lalu jalanin bot.
set -e

REPO_DIR="${AETH_REPO_DIR:-/app/worker-repo}"
GITHUB_REPO="${GITHUB_KEYLIST_REPO:-}"

if [ ! -d "$REPO_DIR/.git" ]; then
  if [ -z "$GITHUB_REPO" ]; then
    echo "ERROR: AETH_REPO_DIR belum ada dan GITHUB_KEYLIST_REPO belum diset."
    echo "Set GITHUB_KEYLIST_REPO ke URL repo (tanpa https://), mis: username/repo"
    exit 1
  fi
  echo "Clone repo keylist..."
  git clone "https://oauth2:${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git" "$REPO_DIR"
  git -C "$REPO_DIR" config user.email "bot@aethernf.local"
  git -C "$REPO_DIR" config user.name "aethbot"
else
  echo "Repo sudah ada, pull terbaru..."
  git -C "$REPO_DIR" pull --rebase --quiet || true
fi

echo "Jalankan bot..."
exec python3 /app/bot.py

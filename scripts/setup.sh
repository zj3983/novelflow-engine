#!/usr/bin/env sh
set -eu

uv sync --extra dev
cd apps/web
npm ci

echo "Setup complete."

#!/usr/bin/env bash
set -euo pipefail

uvicorn apps.api.main:app --reload --port 8000

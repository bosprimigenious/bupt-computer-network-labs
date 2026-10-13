#!/bin/sh
set -u
cd "$(dirname "$0")"
exec _环境/.venv/bin/python _环境/run_all.py "$@"

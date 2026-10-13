#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ "$#" -eq 0 ]; then set -- 实验1; fi
if [ "$1" = "实验6" ]; then
  shift
  exec _环境/.venv/bin/python 实验6/run.py "$@"
fi
exec _环境/.venv/bin/python _环境/lab.py run "$@"

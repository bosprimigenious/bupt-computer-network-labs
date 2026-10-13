#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
command -v brew >/dev/null
command -v uv >/dev/null
if ! command -v dynamips >/dev/null; then
  HOMEBREW_NO_AUTO_UPDATE=1 brew install dynamips
fi
if ! command -v tshark >/dev/null; then
  HOMEBREW_NO_AUTO_UPDATE=1 brew install wireshark
fi
if [ ! -x _环境/.venv/bin/python ]; then
  uv venv _环境/.venv --python 3.11
fi
if ! uv pip sync --offline --python _环境/.venv/bin/python _环境/requirements.lock; then
  uv pip sync --python _环境/.venv/bin/python _环境/requirements.lock
fi
_环境/.venv/bin/python -c 'import configobj, telnetlib3; print("Python依赖就绪")'

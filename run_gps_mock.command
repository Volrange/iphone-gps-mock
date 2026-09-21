#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "请先运行 ./setup.command 安装项目依赖。"
    exit 1
fi
exec .venv/bin/python gps_mock_app.py

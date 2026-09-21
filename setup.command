#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c 'import tkinter; import pymobiledevice3; print("依赖已安装。双击 run_gps_mock.command 启动。")'

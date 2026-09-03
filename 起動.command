#!/bin/bash
# ダブルクリックでアプリを開く。インターネットは不要（127.0.0.1 にしか繋がない）。
cd "$(dirname "$0")"
PORT=8765

# すでに起動していれば使い回す
if ! curl -s -o /dev/null "http://127.0.0.1:$PORT/index.html"; then
  python3 tools/serve.py "$PORT" >/tmp/sc-am2-server.log 2>&1 &
  for _ in $(seq 1 40); do
    curl -s -o /dev/null "http://127.0.0.1:$PORT/index.html" && break
    sleep 0.1
  done
fi

open "http://localhost:$PORT/"
echo "SC試験対策 を http://localhost:$PORT/ で開きました。"
echo "このウィンドウを閉じてもアプリは動き続けます。"
echo "止めるには:  pkill -f tools/serve.py"

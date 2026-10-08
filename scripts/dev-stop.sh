#!/usr/bin/env bash
# Stop DhanDrishti's own dev servers (web :3100, API :4000), including orphaned ones.
# Only processes whose command line is inside this repository are touched.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
stopped=0
for port in 3100 4000; do
  for pid in $(ss -ltnp 2>/dev/null | grep -E ":${port}\b" | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u); do
    # Walk up to the outermost ancestor that still belongs to this repo (turbo / pnpm / tsx / next).
    target=$pid
    p=$pid
    while [[ -n "$p" && "$p" != 1 ]]; do
      cmd=$(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null)
      [[ "$cmd" == *"$ROOT"* || "$cmd" == *"next-server"* || "$cmd" == *"tsx"*"server.ts"* ]] && target=$p
      p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
      [[ "$cmd" == *zsh* || "$cmd" == *bash* || "$cmd" == *warp* ]] && break
    done
    if tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null | grep -qE "$ROOT|next-server|server\.ts"; then
      echo "stopping port $port: pid $pid (group root $target)"
      pkill -TERM -P "$target" 2>/dev/null; kill -TERM "$target" "$pid" 2>/dev/null
      stopped=1
    else
      echo "port $port is used by another program (pid $pid); leaving it alone"
    fi
  done
done
sleep 2
ss -ltn | grep -qE ':(3100|4000)\b' && echo "some ports are still busy" || echo "ports 3100 and 4000 are free"
[[ $stopped == 0 ]] && echo "(no DhanDrishti dev servers were running)"
exit 0

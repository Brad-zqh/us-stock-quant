#!/bin/bash
# 一键安装/卸载每日盘前推送 (macOS launchd)
# 用法: ./setup_daily_push.sh install   |   ./setup_daily_push.sh uninstall
#       ./setup_daily_push.sh test      (立即跑一次, 不依赖定时)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$DIR/com.brad.stockquant.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.brad.stockquant.plist"

case "$1" in
  install)
    if [ ! -f "$DIR/config.json" ]; then
      echo "❌ 未找到 config.json — 请先复制 config.example.json 为 config.json 并填好邮箱授权码/微信SendKey"
      exit 1
    fi
    mkdir -p "$HOME/Library/LaunchAgents"
    cp "$PLIST_SRC" "$PLIST_DST"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo "✅ 已安装定时任务: 每个工作日 08:00 自动推送"
    echo "   日志: $DIR/daily_push.log"
    echo "   改时间: 编辑 $PLIST_DST 里的 Hour/Minute 后重新 install"
    ;;
  uninstall)
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    rm -f "$PLIST_DST"
    echo "🗑️  已卸载定时任务"
    ;;
  test)
    echo "▶️  立即跑一次推送…"
    cd "$DIR" && /opt/anaconda3/bin/python3 run_daily.py
    ;;
  *)
    echo "用法: $0 {install|uninstall|test}"
    exit 1
    ;;
esac

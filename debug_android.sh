#!/usr/bin/env bash
# =============================================================================
# debug_android.sh — ADB crash + log inspector for AI Navigation Assistant
# Your journalctl equivalent for Android.
#
# Usage:
#   ./debug_android.sh live       — live logcat for the app (like journalctl -f)
#   ./debug_android.sh crash      — show latest native crash tombstone
#   ./debug_android.sh kernel     — kernel ring buffer (like journalctl -k)
#   ./debug_android.sh anr        — show latest ANR trace
#   ./debug_android.sh bugreport  — pull full system bug report zip
#   ./debug_android.sh watch      — watch for any new crash and dump it immediately
#   ./debug_android.sh all        — dump logcat + crash + kernel to a timestamped file
# =============================================================================

set -euo pipefail

PKG="com.navigation.assistant"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
REPORT_DIR="$(dirname "$0")/crash_reports"
mkdir -p "$REPORT_DIR"

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; NC='\033[0m'; BOLD='\033[1m'

check_adb() {
    if ! adb devices | grep -q "device$"; then
        echo -e "${RED}ERROR: No ADB device connected. Run 'adb devices' to check.${NC}"
        exit 1
    fi
}

cmd="${1:-help}"

case "$cmd" in
# ── live ──────────────────────────────────────────────────────────────────────
live)
    check_adb
    echo -e "${GREEN}${BOLD}[live]${NC} Tailing logcat for $PKG — Ctrl+C to stop"
    echo -e "${YELLOW}Tip: Kernel messages → ./debug_android.sh kernel${NC}\n"
    PID=$(adb shell pidof "$PKG" 2>/dev/null | tr -d '\r' || true)
    if [ -n "$PID" ]; then
        echo -e "App PID: ${BOLD}$PID${NC}"
        adb logcat --pid="$PID" -v time -v color
    else
        echo -e "${YELLOW}App not running. Showing all logs filtered by tag...${NC}"
        adb logcat -v time NavAssistant:V ai_navigation:V "*:E"
    fi
    ;;

# ── crash ─────────────────────────────────────────────────────────────────────
crash)
    check_adb
    echo -e "${RED}${BOLD}[crash]${NC} Reading latest tombstone from /data/tombstones/"
    
    # Find the most recently modified tombstone
    LATEST=$(adb shell "ls -t /data/tombstones/tombstone_* 2>/dev/null | head -1" | tr -d '\r')
    if [ -z "$LATEST" ]; then
        echo "No tombstones found."
        exit 0
    fi

    echo -e "Latest crash: ${BOLD}$LATEST${NC}"
    echo "─────────────────────────────────────────────────────────────────────"
    
    # Pull and display
    OUT="$REPORT_DIR/tombstone_${TIMESTAMP}.txt"
    adb shell cat "$LATEST" | tee "$OUT"
    
    echo ""
    echo -e "${GREEN}Saved to: $OUT${NC}"
    echo ""
    echo -e "${BOLD}Crash buffer (logcat -b crash):${NC}"
    adb logcat -d -b crash -v time | grep -a "$PKG\|FATAL\|libc\|DEBUG" || true
    ;;

# ── kernel ────────────────────────────────────────────────────────────────────
kernel)
    check_adb
    echo -e "${GREEN}${BOLD}[kernel]${NC} Kernel ring buffer — like 'journalctl -k'"
    echo "─────────────────────────────────────────────────────────────────────"
    if adb shell [ -r /proc/kmsg ] 2>/dev/null; then
        # Continuous kernel log (requires root)
        echo -e "${YELLOW}Live kernel log — Ctrl+C to stop${NC}"
        adb shell su -c "cat /proc/kmsg"
    else
        adb shell dmesg | tail -200
    fi
    ;;

# ── anr ───────────────────────────────────────────────────────────────────────
anr)
    check_adb
    echo -e "${YELLOW}${BOLD}[anr]${NC} ANR traces from /data/anr/"
    LATEST_ANR=$(adb shell "ls -t /data/anr/ 2>/dev/null | head -1" | tr -d '\r')
    if [ -z "$LATEST_ANR" ]; then
        echo "No ANR traces found."
        exit 0
    fi
    OUT="$REPORT_DIR/anr_${TIMESTAMP}.txt"
    echo -e "Latest ANR: ${BOLD}/data/anr/$LATEST_ANR${NC}"
    adb shell cat "/data/anr/$LATEST_ANR" | tee "$OUT"
    echo -e "\n${GREEN}Saved to: $OUT${NC}"
    ;;

# ── bugreport ─────────────────────────────────────────────────────────────────
bugreport)
    check_adb
    echo -e "${BOLD}[bugreport]${NC} Pulling full system report..."
    echo "This takes ~30 seconds. Output goes to $REPORT_DIR/"
    cd "$REPORT_DIR"
    adb bugreport "bugreport_${TIMESTAMP}.zip"
    echo -e "${GREEN}Done: $REPORT_DIR/bugreport_${TIMESTAMP}.zip${NC}"
    echo "Open the zip and look for: bugreport-*/FS/data/tombstones/ and logcat.txt"
    ;;

# ── watch ─────────────────────────────────────────────────────────────────────
watch)
    check_adb
    echo -e "${RED}${BOLD}[watch]${NC} Crash watcher active. Will dump tombstone on any new crash — Ctrl+C to stop"
    PREV_COUNT=$(adb shell "ls /data/tombstones/ 2>/dev/null | wc -l" | tr -d '\r ')
    while true; do
        sleep 2
        NEW_COUNT=$(adb shell "ls /data/tombstones/ 2>/dev/null | wc -l" | tr -d '\r ')
        if [ "$NEW_COUNT" -gt "$PREV_COUNT" ]; then
            echo -e "\n${RED}★ NEW CRASH DETECTED at $(date)${NC}"
            LATEST=$(adb shell "ls -t /data/tombstones/tombstone_* | head -1" | tr -d '\r')
            OUT="$REPORT_DIR/crash_${TIMESTAMP}.txt"
            adb shell cat "$LATEST" | tee "$OUT"
            echo -e "\n${GREEN}Saved: $OUT${NC}\n"
            PREV_COUNT=$NEW_COUNT
        fi
        printf "."
    done
    ;;

# ── all ───────────────────────────────────────────────────────────────────────
all)
    check_adb
    OUT="$REPORT_DIR/debug_all_${TIMESTAMP}.txt"
    echo -e "${BOLD}[all]${NC} Dumping everything to $OUT"
    {
        echo "=== DEVICE INFO ===";   adb shell getprop ro.build.fingerprint
        echo "=== DMESG (last 100) ===" ; adb shell dmesg | tail -100
        echo "=== CRASH BUFFER ===" ; adb logcat -d -b crash -v time
        echo "=== MAIN LOG (last 500 lines) ===" ; adb logcat -d -v time -t 500
        echo "=== LATEST TOMBSTONE ===" 
        LATEST=$(adb shell "ls -t /data/tombstones/tombstone_* 2>/dev/null | head -1" | tr -d '\r')
        [ -n "$LATEST" ] && adb shell cat "$LATEST" || echo "No tombstone found."
    } | tee "$OUT"
    echo -e "${GREEN}Done. File: $OUT${NC}"
    ;;

# ── help / default ────────────────────────────────────────────────────────────
*)
    echo -e "${BOLD}AI Navigation Assistant — Android Debug Helper${NC}"
    echo ""
    echo "Usage: ./debug_android.sh <command>"
    echo ""
    echo "  live       Live logcat for the app (like: journalctl -f -u myapp)"
    echo "  crash      Latest native crash tombstone (like: coredumpctl show)"
    echo "  kernel     Kernel ring buffer (like: journalctl -k)"
    echo "  anr        Latest ANR trace (app-not-responding event)"
    echo "  bugreport  Full system bug report zip (takes ~30s)"
    echo "  watch      Monitor and auto-dump on new crashes"
    echo "  all        Dump everything to a timestamped file"
    echo ""
    echo -e "${YELLOW}Tip: Run 'adb root' first if some commands say 'permission denied'${NC}"
    ;;
esac

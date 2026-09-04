#!/usr/bin/env bash
#
# Shared: put a real browser on screen on a headless server, reachable over
# an SSH tunnel. Sourced by outreach-login.sh and outreach-watch.sh — one
# implementation, so a fix to the display or the password handling lands in
# both.
#
# Callers get:
#     vnc_require_deps          install Xvfb + x11vnc if missing
#     vnc_start                 start the display and server; exports DISPLAY
#     vnc_banner "<what>"       print the password and connection guidance
#     vnc_cleanup               kill everything and delete the password file
#
# The caller owns the trap, because it usually has its own cleanup to do:
#     trap 'my_cleanup; vnc_cleanup' EXIT INT TERM
#
# shellcheck shell=bash

VNC_DISPLAY_NUM="${ICREATE_LOGIN_DISPLAY:-99}"
VNC_PORT="${ICREATE_LOGIN_VNC_PORT:-5900}"
VNC_PASS=""
_VNC_XVFB_PID=""
_VNC_X11VNC_PID=""
_VNC_PASSFILE=""

vnc_require_deps() {
    if command -v x11vnc >/dev/null 2>&1 && command -v Xvfb >/dev/null 2>&1; then
        return 0
    fi
    echo "==> Installing Xvfb + x11vnc (first run only, takes a minute)"
    # NEEDRESTART_MODE=a stops the post-install service scanner from
    # scribbling over the calling script's output.
    export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1
    apt-get update -qq
    apt-get install -y -qq xvfb x11vnc >/dev/null 2>&1
}

vnc_cleanup() {
    [ -n "$_VNC_X11VNC_PID" ] && kill "$_VNC_X11VNC_PID" 2>/dev/null || true
    [ -n "$_VNC_XVFB_PID" ] && kill "$_VNC_XVFB_PID" 2>/dev/null || true
    [ -n "$_VNC_PASSFILE" ] && rm -f "$_VNC_PASSFILE" 2>/dev/null || true
    rm -f "/tmp/.X${VNC_DISPLAY_NUM}-lock" 2>/dev/null || true
}

# vnc_start <path-to-python>
vnc_start() {
    local python_bin=$1

    echo "==> Starting virtual display :$VNC_DISPLAY_NUM"
    Xvfb ":$VNC_DISPLAY_NUM" -screen 0 1280x900x24 >/dev/null 2>&1 &
    _VNC_XVFB_PID=$!
    sleep 2

    # A one-time password, regenerated every run and deleted on exit.
    #
    # The real security boundary is -localhost: the port is not reachable
    # from the internet, only through an SSH tunnel by someone who already
    # has access to this box. The password exists because macOS Screen
    # Sharing refuses to connect to a VNC server offering no authentication
    # — it prompts, with nothing valid to type.
    #
    # Generated with python, not `tr </dev/urandom | head -c 8`: under the
    # callers' `set -euo pipefail`, head closing the pipe kills tr with
    # SIGPIPE and the whole script exits silently. VNC truncates past 8
    # characters anyway.
    VNC_PASS=$("$python_bin" -c \
        "import secrets; print(''.join(secrets.choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(8)))")
    _VNC_PASSFILE=$(mktemp /tmp/.icf-vncpw-XXXXXX)
    chmod 600 "$_VNC_PASSFILE"
    x11vnc -storepasswd "$VNC_PASS" "$_VNC_PASSFILE" >/dev/null 2>&1

    echo "==> Starting VNC on 127.0.0.1:$VNC_PORT (localhost only)"
    x11vnc -display ":$VNC_DISPLAY_NUM" -rfbport "$VNC_PORT" -localhost \
           -rfbauth "$_VNC_PASSFILE" -forever -shared -quiet >/dev/null 2>&1 &
    _VNC_X11VNC_PID=$!
    sleep 2

    export DISPLAY=":$VNC_DISPLAY_NUM"
}

# vnc_banner "<what you'll see>" "<what ends it>"
vnc_banner() {
    local what=$1
    local ending=$2
    cat <<BANNER

  ─────────────────────────────────────────────────────────────
   Screen Sharing will ask for a password. Use this one:

           $VNC_PASS

   NOT your Mac password. It is generated for this session
   only and is thrown away when this finishes.

   $what

   $ending

   If the window doesn't open by itself, press Cmd-K in Finder
   and enter:   vnc://localhost:$VNC_PORT
  ─────────────────────────────────────────────────────────────

BANNER
}

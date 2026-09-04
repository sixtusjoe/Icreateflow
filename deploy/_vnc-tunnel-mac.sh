#!/usr/bin/env bash
#
# Shared Mac side: tunnel to the server's VNC and open Screen Sharing on it.
# Sourced by outreach-login-mac.sh and outreach-watch-mac.sh.
#
#     tunnel_open           opens the tunnel, arms the viewer, sets PORT
#     tunnel_close          tears the tunnel down (call from your trap)
#
# shellcheck shell=bash

HOST="${ICREATE_HOST:-root@95.111.228.80}"
REMOTE_PORT="${ICREATE_LOGIN_VNC_PORT:-5900}"
PORT="$REMOTE_PORT"
_TUNNEL_CTL=""

tunnel_close() {
    if [ -n "$_TUNNEL_CTL" ]; then
        ssh -S "$_TUNNEL_CTL" -O exit "$HOST" 2>/dev/null || true
        rm -f "$_TUNNEL_CTL"
        _TUNNEL_CTL=""
    fi
}

tunnel_open() {
    # macOS enables its own screen sharing on 5900; step aside if it's in use.
    if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        PORT=5901
        echo "==> Port $REMOTE_PORT is busy on this Mac, using $PORT instead"
    fi

    echo "==> Opening tunnel to $HOST"
    _TUNNEL_CTL="/tmp/icreateflow-vnc-$$"
    ssh -M -S "$_TUNNEL_CTL" -f -N -L "$PORT:localhost:$REMOTE_PORT" "$HOST"

    # Wait for the VNC server to actually answer before opening the viewer.
    #
    # A fixed delay is wrong: the first run on a box installs Xvfb and
    # x11vnc first, which takes far longer than any sensible guess, and
    # connecting early just gives "Connection failed to localhost".
    #
    # A bare connect is not enough either — the tunnel's local port is bound
    # by ssh immediately, so connecting succeeds even when nothing is
    # listening on the far end. A real VNC server greets us with an
    # "RFB 003.00x" banner, so wait for that.
    #
    # Read it over bash's /dev/tcp rather than `nc … | head -c 3 | grep`:
    # under `pipefail`, head closing the pipe can kill nc with SIGPIPE and
    # make the whole condition report failure even when the banner arrived.
    (
        for _ in $(seq 1 150); do   # up to ~5 minutes
            if read -r -t 3 banner < "/dev/tcp/localhost/$PORT" 2>/dev/null \
               && [ "${banner:0:3}" = "RFB" ]
            then
                sleep 1
                echo
                echo "==> Opening Screen Sharing."
                open "vnc://localhost:$PORT" 2>/dev/null || {
                    echo "!!  Couldn't open Screen Sharing automatically."
                    echo "!!  In Finder press Cmd-K and enter:  vnc://localhost:$PORT"
                }
                exit 0
            fi
            sleep 2
        done
        echo
        echo "!!  The server's VNC never came up. Once you see 'Starting VNC'"
        echo "!!  above, press Cmd-K in Finder and enter:  vnc://localhost:$PORT"
    ) &
}

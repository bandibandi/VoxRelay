#!/usr/bin/env bash
# Sits in a terminal window and runs the commands approved in the voice
# command dialog. Reads them one per line from a named pipe.
#
# The pipe is opened read-write (3<>) on purpose: that keeps a writer end
# open inside this shell, so the loop never sees EOF when the sender
# disconnects between commands.

FIFO="$1"
LOG="$2"

printf '\033]0;Voice command runner\007'
printf '\033[1mVoice command runner\033[0m\n'
printf 'Approved commands run here. Close this window to stop it.\n'

exec 3<> "$FIFO"

while read -r line <&3; do
    printf '\n\033[1;32m$\033[0m %s\n' "$line"

    if [ -n "$LOG" ]; then
        eval "$line" 2>&1 | tee -a "$LOG"
    else
        eval "$line" 2>&1
    fi
done

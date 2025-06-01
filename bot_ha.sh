#!/bin/bash

ACTION=$1
LOGFILE="/var/log/bot_ha.log"

echo "$(date): Script triggered with action: $ACTION" >> "$LOGFILE"

if [ "$ACTION" == "master" ]; then
    echo "$(date): Sleeping for 5 seconds to avoid race condition..." >> "$LOGFILE"
    sleep 5

    echo "$(date): Starting bot..." >> "$LOGFILE"
    cd /home/robin/project || { echo "Failed to cd to project folder" >> "$LOGFILE"; exit 1; }
    /usr/bin/python3 bot.py >> "$LOGFILE" 2>&1 &

elif [ "$ACTION" == "backup" ]; then
    echo "$(date): Stopping bot..." >> "$LOGFILE"
    pkill -f "python3 bot.py"
fi

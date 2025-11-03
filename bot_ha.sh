#!/bin/bash

ACTION=$1
LOGFILE="/var/log/bot_ha.log"

# Detect correct project directory
if [ -d "/home/robin/project" ]; then
    PROJECT_DIR="/home/robin/project"
elif [ -d "/root/project" ]; then
    PROJECT_DIR="/root/project"
else
    echo "$(date): ERROR - project folder not found!" >> "$LOGFILE"
    exit 1
fi

echo "$(date): Script triggered with action: $ACTION" >> "$LOGFILE"

if [ "$ACTION" == "master" ]; then
    echo "$(date): Sleeping for 5 seconds to avoid race condition..." >> "$LOGFILE"
    sleep 5

    echo "$(date): Starting bot in $PROJECT_DIR..." >> "$LOGFILE"
    cd "$PROJECT_DIR" || { echo "Failed to cd to $PROJECT_DIR" >> "$LOGFILE"; exit 1; }
    /usr/bin/python3 bot.py >> "$LOGFILE" 2>&1 &

elif [ "$ACTION" == "backup" ]; then
    echo "$(date): Stopping bot..." >> "$LOGFILE"
    pkill -f "python3 bot.py"
fi

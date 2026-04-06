#!/bin/bash

ACTION="$1"
LOGFILE="/var/log/bot_ha.log"
SERVICE_NAME="telegram-bot"

log() {
    echo "$(date): $1" >> "$LOGFILE"
}

log "Script triggered with action: ${ACTION:-unknown}"

case "$ACTION" in
    master)
        log "Waiting briefly before starting ${SERVICE_NAME}."
        sleep 5
        systemctl start "$SERVICE_NAME"
        ;;
    backup|fault)
        log "Stopping ${SERVICE_NAME}."
        systemctl stop "$SERVICE_NAME"
        ;;
    *)
        log "Unknown action: ${ACTION:-empty}"
        exit 1
        ;;
esac

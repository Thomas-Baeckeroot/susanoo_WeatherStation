#!/usr/bin/env bash
# Web server launcher with automatic restart; install as a Synology rc.d script (run as root):
#   cp bin/susanoo_WeatherStation_startWebServer.sh /usr/local/etc/rc.d/weatherStationWeb.sh
# Usage: weatherStationWeb.sh {start|stop|restart|status}

WEB_USER="web"
PY_VENV="/usr/local/share/susanoo-py-venv"
SERVER="/var/services/homes/meteo/meteo/src/main/py/server3.py"
WORK_DIR="/var/services/homes/web/public_html"
LOG_FILE="/var/services/homes/web/susanoo-web.log"
PID_FILE="/var/run/susanoo-web-supervisor.pid"
# Lets the database and network come up when started at boot
START_DELAY="${START_DELAY:-60}"

log() {
    printf -- "%s - %s\n" "$(date)" "$*" >> "${LOG_FILE}"
}

is_running() {
    [ -f "${PID_FILE}" ] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null
}

supervise() {
    sleep "${START_DELAY}"
    cd "${WORK_DIR}" || { log "Cannot cd to ${WORK_DIR}"; exit 1; }
    while [ -f "${PID_FILE}" ]; do
        log "Starting meteo server from $0"
        started=$(date +%s)
        # The venv's python3 is called explicitly: sudo may reset PATH
        sudo -u "${WEB_USER}" env PYTHONUNBUFFERED=1 "${PY_VENV}/bin/python3" "${SERVER}" >> "${LOG_FILE}" 2>&1
        exit_code=$?
        [ -f "${PID_FILE}" ] || break
        # Back off when it dies right away (e.g. broken venv) to avoid flooding the log
        if [ $(( $(date +%s) - started )) -lt 60 ]; then pause=60; else pause=10; fi
        log "Meteo server exited with code ${exit_code}, restarting in ${pause} s"
        sleep "${pause}"
    done
    log "Meteo server supervisor stopped"
}

start() {
    if is_running; then
        echo "Already running (supervisor PID $(cat "${PID_FILE}"))"
        return 0
    fi
    echo $$ > "${PID_FILE}"
    supervise < /dev/null > /dev/null 2>&1 &
    echo $! > "${PID_FILE}"
    echo "Started (supervisor PID $!), server starts in ${START_DELAY} s"
}

stop() {
    if [ -f "${PID_FILE}" ]; then
        supervisor=$(cat "${PID_FILE}")
        rm -f "${PID_FILE}"
        pkill -f "${SERVER}"
        kill "${supervisor}" 2>/dev/null
        echo "Stopped"
    else
        pkill -f "${SERVER}" && echo "Stopped (no supervisor)"
    fi
}

case "$1" in
    start|"") start ;;
    stop) stop ;;
    restart) stop; sleep 2; START_DELAY=0 start ;;
    status)
        if is_running; then echo "Supervisor running (PID $(cat "${PID_FILE}"))"; else echo "Supervisor not running"; fi
        pgrep -af "${SERVER}" || echo "Server not running"
        ;;
    *) echo "Usage: $0 {start|stop|restart|status}"; exit 1 ;;
esac
exit 0

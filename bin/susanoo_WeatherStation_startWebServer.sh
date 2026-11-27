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
# Command line of the server, as started below (also part of the command lines of the sudo / env / sh
# starting it). stop / status match it whole, so that e.g. an editor open on server3.py is never killed.
SERVER_COMMAND="${PY_VENV}/bin/python3 ${SERVER}"
# Lets the database and network come up when started at boot
START_DELAY="${START_DELAY:-60}"

# The log is shared with the server and its CGI scripts (run as ${WEB_USER}) and lives in the home folder of
# ${WEB_USER}: although this script runs as root, it only ever writes the log as ${WEB_USER}. Root opening,
# creating or chown-ing a path in a folder ${WEB_USER} controls would follow a symlink planted there, letting
# ${WEB_USER} write to (or take) any file. Written as ${WEB_USER}, the log also gets the right owner when it
# is created (fresh install, or deleted meanwhile).
log() {
    printf -- "%s - %s\n" "$(date)" "$*" | sudo -u "${WEB_USER}" tee -a "${LOG_FILE}" > /dev/null
}

# The supervisor runs as its own process, '<bash> <this script> __supervise' (see start()). The PID file can
# outlive it (killed by SIGKILL or the OOM killer) and its PID be reused later by an unrelated process: only trust
# it while that process still has this marker argument. A fixed marker, not this script's name: the repository
# copy and the rc.d copy (different names) must recognise each other's supervisor.
SUPERVISOR_MARKER="__supervise"
is_running() {
    [ -f "${PID_FILE}" ] && ps -p "$(cat "${PID_FILE}")" -o args= 2>/dev/null | grep -q -E -- " ${SUPERVISOR_MARKER}\$"
}

supervise() {
    sleep "${START_DELAY}"
    # No PID file left behind: its PID could later be reused by an unrelated process
    cd "${WORK_DIR}" || { log "Cannot cd to ${WORK_DIR}"; rm -f "${PID_FILE}"; exit 1; }
    while [ -f "${PID_FILE}" ]; do
        log "Starting meteo server from $0"
        started=$(date +%s)
        # The venv's python3 is called explicitly: sudo may reset PATH. The output redirection is opened by the
        # sh run as ${WEB_USER} (see log() above), which then becomes the server (exec).
        sudo -u "${WEB_USER}" env PYTHONUNBUFFERED=1 sh -c 'exec "$1" "$2" >> "$3" 2>&1' sh \
            "${PY_VENV}/bin/python3" "${SERVER}" "${LOG_FILE}"
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
    # Said here, where someone reads the output: the server cannot start if ${WEB_USER} cannot write its log
    # (e.g. a file left owned by root by an older version of this script: chown it to ${WEB_USER} once).
    log "Supervisor started by $0" 2> /dev/null \
        || echo "Warning: ${WEB_USER} cannot write ${LOG_FILE}, the server will not start" >&2
    echo $$ > "${PID_FILE}"  # the supervisor's loop runs while this file exists
    START_DELAY="${START_DELAY}" "${BASH:-bash}" "$0" "${SUPERVISOR_MARKER}" < /dev/null > /dev/null 2>&1 &
    echo $! > "${PID_FILE}"
    echo "Started (supervisor PID $!), server starts in ${START_DELAY} s"
}

# Synology DSM has pkill (procps-ng), only pgrep is missing (see status below).
stop() {
    if [ -f "${PID_FILE}" ]; then
        supervisor=""
        if is_running; then supervisor=$(cat "${PID_FILE}"); fi
        # Without the PID file, a supervisor not killed below (stale PID file) stops once its server is gone
        rm -f "${PID_FILE}"
        pkill -f "${SERVER_COMMAND}"
        [ -n "${supervisor}" ] && kill "${supervisor}" 2>/dev/null
        echo "Stopped"
    else
        pkill -f "${SERVER_COMMAND}" && echo "Stopped (no supervisor)"
    fi
}

case "$1" in
    start|"") start ;;
    stop) stop ;;
    restart) stop; sleep 2; START_DELAY=0 start ;;
    "${SUPERVISOR_MARKER}") supervise ;;  # started by start() only
    status)
        if is_running; then echo "Supervisor running (PID $(cat "${PID_FILE}"))"; else echo "Supervisor not running"; fi
        # No pgrep on Synology DSM. The second grep drops the first one, whose command line contains the pattern.
        ps -eo user,pid,args | grep -F -- "${SERVER_COMMAND}" | grep -v -F -- "grep -F" || echo "Server not running"
        ;;
    *) echo "Usage: $0 {start|stop|restart|status}"; exit 1 ;;
esac
exit 0

#!/usr/bin/env bash
# Gives the web server its own MariaDB account, allowed to read the database only (SELECT), and writes it to the
# web server's config. Run by an administrator once the data collector is installed and configured (its config
# gives the database name and port); run it again at any time to renew the password.
#
# Why:
# - The web server is exposed to the internet and only reads the database: with a read-only account, a flaw in
#   the web code can neither modify nor delete measures.
# - The web server has its own config, never the collector's one nor a link to it: the collector's config holds
#   its read-write account and the accounts of the remote stations. Once the web server has its own config, the
#   collector's one is made private (mode 600).
# - The password is random and only stored in the web server's config (mode 600) and in MariaDB: nobody types
#   it, and it never appears on a command line (visible with 'ps') nor in a shell or MariaDB client history.
#
# Usage: bin/create_web_db_account.sh [COLLECTOR_USER] [WEB_USER]
#   COLLECTOR_USER  user of the data collector (default: owner of this repository)
#   WEB_USER        user of the web server (default: web); also the name of its MariaDB account
# Environment:
#   MYSQL           MariaDB client command, as an account allowed to create users, reading SQL on its standard
#                   input. Default 'sudo mariadb -u root' (Raspberry Pi OS: MariaDB's root is the Unix root).
#                   Synology NAS: MYSQL='/usr/local/mariadb10/bin/mariadb -u root -p' (asks for the password).
#   PY_VENV         Python venv of the web server, to check the new account (default /usr/local/share/susanoo-py-venv)
#   DB_ACCOUNT_HOST host part of the account (default localhost: the web server runs on the database's host)
#   SUSANOO_CONFIG / WEB_CONFIG  config files of the collector / web server (default: in their home folders)
set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
REPOSITORY=$(dirname "${SCRIPT_DIR}")
COLLECTOR_USER="${1:-$(ls -ld "${REPOSITORY}" | awk '{print $3}')}"
WEB_USER="${2:-web}"
MYSQL="${MYSQL:-sudo mariadb -u root}"
PY_VENV="${PY_VENV:-/usr/local/share/susanoo-py-venv}"
DB_ACCOUNT_HOST="${DB_ACCOUNT_HOST:-localhost}"

# Runs a command as another user, with that user's HOME (where its config is)
run_as() {
    local user="$1"
    shift
    if [ "${user}" = "$(id -un)" ]; then "$@"; else sudo -H -u "${user}" "$@"; fi
}

home_of() {
    run_as "$1" sh -c 'printf "%s" "${HOME}"'
}

# Value of a key (case-insensitive, like Python's configparser) in a section of a config file, read by its owner
ini_setting() {
    local user="$1" file="$2" section="$3" key="$4"
    run_as "${user}" awk -v section="${section}" -v key="${key}" '
        /^[ \t]*\[/ { name = $0; gsub(/^[ \t]*\[|\][ \t\r]*$/, "", name); in_section = (tolower(name) == section); next }
        in_section && /=/ {
            name = $0; sub(/[ \t]*=.*/, "", name); gsub(/^[ \t]+/, "", name)
            if (tolower(name) == key) { sub(/^[^=]*=[ \t]*/, ""); sub(/[ \t\r]+$/, ""); print; exit }
        }' "${file}" 2> /dev/null || true
}

valid_name() {
    [[ "$1" =~ ^[A-Za-z0-9_]+$ ]] || { echo "Invalid $2: '$1'" >&2; exit 1; }
}

COLLECTOR_CONFIG="${SUSANOO_CONFIG:-$(home_of "${COLLECTOR_USER}")/.config/susanoo_WeatherStation.conf}"
WEB_CONFIG="${WEB_CONFIG:-$(home_of "${WEB_USER}")/.config/susanoo_WeatherStation.conf}"

DB_NAME=$(ini_setting "${COLLECTOR_USER}" "${COLLECTOR_CONFIG}" database name)
DB_NAME="${DB_NAME:-weather_station}"
DB_PORT=$(ini_setting "${COLLECTOR_USER}" "${COLLECTOR_CONFIG}" database port)
DB_PORT="${DB_PORT:-3306}"
valid_name "${WEB_USER}" "web user"
valid_name "${DB_NAME}" "database name"
[[ "${DB_PORT}" =~ ^[0-9]+$ ]] || { echo "Invalid database port: '${DB_PORT}'" >&2; exit 1; }
[[ "${DB_ACCOUNT_HOST}" =~ ^[A-Za-z0-9_.%-]+$ ]] || { echo "Invalid account host: '${DB_ACCOUNT_HOST}'" >&2; exit 1; }
# Settings of the web server itself, kept from its current config (possibly still the collector's one)
WEB_PORT=$(ini_setting "${WEB_USER}" "${WEB_CONFIG}" default webserverport)
WEB_HOST=$(ini_setting "${WEB_USER}" "${WEB_CONFIG}" default webserverhost)

printf -- "Read-only MariaDB account '%s'@'%s' on database '%s' (port %s), written to %s\n" \
    "${WEB_USER}" "${DB_ACCOUNT_HOST}" "${DB_NAME}" "${DB_PORT}" "${WEB_CONFIG}"

# Hexadecimal: nothing to escape in SQL, and no '%' (Python's configparser would read '%' as interpolation)
PASSWORD=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
[ "${#PASSWORD}" -eq 48 ] || { echo "Could not generate a password" >&2; exit 1; }

# The new config is written next to the current one first, and only replaces it once the account works
NEW_CONFIG="${WEB_CONFIG}.new"
{
    echo "# Config of the web server, written by bin/create_web_db_account.sh (run it again to renew the password)."
    echo "# Private to ${WEB_USER} (mode 600). Its MariaDB account can only read the database."
    echo "[DEFAULT]"
    [ -n "${WEB_PORT}" ] && echo "WebServerPort = ${WEB_PORT}"
    [ -n "${WEB_HOST}" ] && echo "WebServerHost = ${WEB_HOST}"
    echo
    echo "[DATABASE]"
    echo "Name = ${DB_NAME}"
    echo "Port = ${DB_PORT}"
    echo "User = ${WEB_USER}"
    echo "Password = ${PASSWORD}"
} | run_as "${WEB_USER}" sh -c 'umask 077 && mkdir -p "$(dirname "$1")" && cat > "$1"' sh "${NEW_CONFIG}"

# REVOKE first: exactly SELECT on the database, even for an account that existed with more rights
# Through a pipe from the shell's printf (a builtin): the password is in no command line nor temporary file
if ! printf -- "%s\n" \
        "CREATE USER IF NOT EXISTS '${WEB_USER}'@'${DB_ACCOUNT_HOST}' IDENTIFIED BY '${PASSWORD}';" \
        "ALTER USER '${WEB_USER}'@'${DB_ACCOUNT_HOST}' IDENTIFIED BY '${PASSWORD}';" \
        "REVOKE ALL PRIVILEGES, GRANT OPTION FROM '${WEB_USER}'@'${DB_ACCOUNT_HOST}';" \
        "GRANT SELECT ON \`${DB_NAME}\`.* TO '${WEB_USER}'@'${DB_ACCOUNT_HOST}';" | ${MYSQL}
then
    run_as "${WEB_USER}" rm -f "${NEW_CONFIG}"
    echo "Could not create the MariaDB account: the web server's config is unchanged" >&2
    exit 1
fi
unset PASSWORD

# Checked as the web server connects (pymysql, TCP to localhost), before replacing its config
CHECK='
import configparser, re, sys
import pymysql
config = configparser.ConfigParser()
config.read(sys.argv[1])
db = config["DATABASE"]
conn = pymysql.connect(host="localhost", port=db.getint("port", 3306), user=db["user"], password=db["password"],
                       database=db.get("name", "weather_station"))
curs = conn.cursor()
curs.execute("SHOW GRANTS")
for (grant,) in curs.fetchall():
    print("   " + re.sub(r" IDENTIFIED BY .*", "", grant))
'
if ! run_as "${WEB_USER}" "${PY_VENV}/bin/python3" -c "${CHECK}" "${NEW_CONFIG}"; then
    run_as "${WEB_USER}" rm -f "${NEW_CONFIG}"
    echo "The new account does not work for ${WEB_USER}: its config is unchanged" >&2
    exit 1
fi

# A previous config of its own is kept (private); a link (e.g. to the collector's config) is just replaced
if [ -f "${WEB_CONFIG}" ] && ! [ -L "${WEB_CONFIG}" ]; then
    run_as "${WEB_USER}" sh -c 'umask 077 && cp "$1" "$1.bak" && chmod 600 "$1.bak"' sh "${WEB_CONFIG}"
    printf -- "Previous config kept as %s.bak\n" "${WEB_CONFIG}"
fi
run_as "${WEB_USER}" mv -f "${NEW_CONFIG}" "${WEB_CONFIG}"
printf -- "Web server config written (mode 600): its CGI scripts use the new account from their next request.\n"

# The web server no longer reads the collector's config: private to the collector from now on. Copied, then
# renamed over the original: that also gives it to the collector if another user owned it.
if [ -f "${COLLECTOR_CONFIG}" ] && [ "${COLLECTOR_USER}" != "${WEB_USER}" ]; then
    run_as "${COLLECTOR_USER}" sh -c 'umask 077 && cp "$1" "$1.tmp" && chmod 600 "$1.tmp" && mv -f "$1.tmp" "$1"' sh "${COLLECTOR_CONFIG}"
    printf -- "Collector config made private: %s\n" "${COLLECTOR_CONFIG}"
fi

#!/bin/bash
# Purpose = Backup of meteo DB and scripts
# DB settings are read from the [DATABASE] section of the collector's config, as the Python code does
CONFIG_FILE="${SUSANOO_CONFIG:-${HOME}/.config/susanoo_WeatherStation.conf}"
BACKUP_DIR="/volume1/homes/meteo"
DATE=$(date +"%Y-%m-%d")

# Prints the value of a key (case-insensitive, like Python's configparser) from the [DATABASE] section
db_setting() {
    awk -v key="$1" '
        /^[ \t]*\[/ { in_db = (tolower($0) ~ /^[ \t]*\[database\]/); next }
        in_db && /=/ {
            name = $0; sub(/[ \t]*=.*/, "", name); gsub(/^[ \t]+/, "", name)
            if (tolower(name) == key) { sub(/^[^=]*=[ \t]*/, ""); sub(/[ \t\r]+$/, ""); print; exit }
        }' "${CONFIG_FILE}"
}

if [ ! -r "${CONFIG_FILE}" ]; then
    echo "Cannot read ${CONFIG_FILE}" >&2
    exit 1
fi
DBNAME=$(db_setting name)
DBNAME="${DBNAME:-weather_station}"
DBUSER=$(db_setting user)
DBPASSWORD=$(db_setting password)
DBPORT=$(db_setting port)

# Password goes through a private option file rather than the command line, where 'ps' would show it
CREDENTIALS=$(mktemp)
trap 'rm -f "${CREDENTIALS}"' EXIT
chmod 600 "${CREDENTIALS}"
ESCAPED_PASSWORD=$(printf '%s' "${DBPASSWORD}" | sed 's/\\/\\\\/g; s/"/\\"/g')
{
    echo "[client]"
    echo "user=${DBUSER}"
    echo "password=\"${ESCAPED_PASSWORD}\""
    [ -n "${DBPORT}" ] && echo "port=${DBPORT}"
} > "${CREDENTIALS}"

# Option --show-progress-size not available yet on mysqldump v10.19
# --defaults-extra-file must be the first option
nice -n 19 mysqldump --defaults-extra-file="${CREDENTIALS}" --databases "${DBNAME}" > "${BACKUP_DIR}/mysqldump_${DBNAME}_${DATE}.sql"
nice -n 19 gzip "${BACKUP_DIR}/mysqldump_${DBNAME}_${DATE}.sql"

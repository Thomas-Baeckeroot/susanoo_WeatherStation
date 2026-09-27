# Sourced by the DB scripts (backup.sh, db_migrate.sh): reads the [DATABASE] section of the config,
# as the Python code does, and writes the credentials to a private MariaDB option file.
CONFIG_FILE="${SUSANOO_CONFIG:-${HOME}/.config/susanoo_WeatherStation.conf}"

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

# Password goes through a private option file rather than the command line, where 'ps' would show it.
# Pass it as the first option: --defaults-extra-file="${DB_CREDENTIALS}"
DB_CREDENTIALS=$(mktemp)
trap 'rm -f "${DB_CREDENTIALS}"' EXIT
chmod 600 "${DB_CREDENTIALS}"
{
    echo "[client]"
    echo "user=$(db_setting user)"
    echo "password=\"$(db_setting password | sed 's/\\/\\\\/g; s/"/\\"/g')\""
    DBPORT=$(db_setting port)
    [ -n "${DBPORT}" ] && echo "port=${DBPORT}"
} > "${DB_CREDENTIALS}"

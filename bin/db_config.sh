# Sourced by the DB scripts (backup.sh, db_migrate.sh): reads the [DATABASE] section of the config,
# as the Python code does, and writes the credentials to a private MariaDB option file.
CONFIG_FILE="${SUSANOO_CONFIG:-${HOME}/.config/susanoo_WeatherStation.conf}"

# Prints the value of a key (case-insensitive, like Python's configparser) from the [DATABASE] section.
# '%%' is read as '%', as by the Python code (ConfigParser's default interpolation): a password containing
# '%' must be written with '%%' in the config, otherwise Python fails to read it.
db_setting() {
    awk -v key="$1" '
        /^[ \t]*\[/ { in_db = (tolower($0) ~ /^[ \t]*\[database\]/); next }
        in_db && /=/ {
            name = $0; sub(/[ \t]*=.*/, "", name); gsub(/^[ \t]+/, "", name)
            if (tolower(name) == key) {
                sub(/^[^=]*=[ \t]*/, ""); sub(/[ \t\r]+$/, ""); gsub(/%%/, "%"); print; exit
            }
        }' "${CONFIG_FILE}"
}

if [ ! -r "${CONFIG_FILE}" ]; then
    # e.g. a Synology scheduled task left with its default user, root
    echo "Cannot read ${CONFIG_FILE}: run this script as the data-collector user (meteo on the NAS)," \
         "or set SUSANOO_CONFIG to its config file" >&2
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
    # Same connection as the Python code (pymysql, see get_conn()): TCP to localhost on the configured port,
    # so it works wherever the data collector works (e.g. not a 'user'@'localhost' account when the server
    # has skip_name_resolve). Without 'protocol', the mysql clients would use their compiled-in Unix socket
    # for 'localhost' and ignore the port, possibly reaching another MariaDB instance than the Python code.
    echo "protocol=TCP"
    echo "host=localhost"
    DBPORT=$(db_setting port)
    echo "port=${DBPORT:-3306}"
} > "${DB_CREDENTIALS}"

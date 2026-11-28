#!/usr/bin/env bash
set -e
set +x
# set -x

# Constants
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
printf -- "Script directory: '%s'\n" "${SCRIPT_DIR}"
START_DIR=$(pwd)
source "${SCRIPT_DIR}/bin/helper_functions.sh"

# Config files: one per user, each private to its user (mode 600). The collector's one holds its read-write
# database account and the accounts of the remote stations; the web server's one only its read-only account
# (written by bin/create_web_db_account.sh). Never link the web server's config to the collector's one.
COLLECTOR_CONFIG="${HOME}/.config/susanoo_WeatherStation.conf"
function install_config_files() {
  mkdir -p "${HOME}/.config"
  if [ -f "${COLLECTOR_CONFIG}" ]; then
    printf -- "An existing config file has been found\n"
    printf -- "Here is a diff of current version vs. template:\n"
    diff "${COLLECTOR_CONFIG}" "${SCRIPT_DIR}/bin/susanoo_WeatherStation_template.conf" || true
  else
    printf -- "No pre-existing config file found\n"
    (umask 077 && cp "${SCRIPT_DIR}/bin/susanoo_WeatherStation_template.conf" "${COLLECTOR_CONFIG}")
    printf -- "New config file has been copied for user collecting the sensors data.\n"
  fi
  chmod 600 "${COLLECTOR_CONFIG}"
  printf -- "After install script is done, adjust it with:\n"
  printf -- "vi %s\n\n" "${COLLECTOR_CONFIG}"
  read -r -p "Press Enter to continue..."

  # Written as the web user: it owns its config, and the installing user cannot write in its home folder
  if sudo -H -u "${WEB_USER}" sh -c 'test -f "${HOME}/.config/susanoo_WeatherStation.conf"'; then
    printf -- "Existing config file of the web server kept\n"
  else
    sudo -H -u "${WEB_USER}" sh -c 'umask 077 && mkdir -p "${HOME}/.config" && cat > "${HOME}/.config/susanoo_WeatherStation.conf"' \
      < "${SCRIPT_DIR}/bin/susanoo_WeatherStation_Web_template.conf"
    printf -- "New config file has been copied for web server (its database account is set below).\n"
  fi
}

# Value of a key (case-insensitive, like Python's configparser) in the [DATABASE] section of the collector's config
function collector_db_setting() {
  awk -v key="$1" '
    /^[ \t]*\[/ { in_db = (tolower($0) ~ /^[ \t]*\[database\]/); next }
    in_db && /=/ {
      name = $0; sub(/[ \t]*=.*/, "", name); gsub(/^[ \t]+/, "", name)
      if (tolower(name) == key) { sub(/^[^=]*=[ \t]*/, ""); sub(/[ \t\r]+$/, ""); print; exit }
    }' "${COLLECTOR_CONFIG}"
}

# Replaces the password of the [DATABASE] section of the collector's config (kept private)
function set_collector_db_password() {
  (umask 077 && awk -v password="$1" '
    /^[ \t]*\[/ { in_db = (tolower($0) ~ /^[ \t]*\[database\]/) }
    in_db && tolower($0) ~ /^[ \t]*password[ \t]*=/ { print "password = " password; next }
    { print }' "${COLLECTOR_CONFIG}" > "${COLLECTOR_CONFIG}.tmp")
  mv -f "${COLLECTOR_CONFIG}.tmp" "${COLLECTOR_CONFIG}"
}


# todo Below attributions should be replaced by a call to func. that manages a config file ~/.config/susanoo_WeatherStation.conf (GPIO numbers also could be informed there)
# Parsing of .ini/.conf files from bash is described:
#   here:     https://ajdiaz.wordpress.com/2008/02/09/bash-ini-parser/
#   or there: https://github.com/rudimeier/bash_ini_parser
printf -- "\n"
WEB_USER=$(ask_with_default "Inform user to run the Web server or press ENTER for default" "web")

printf -- "\nInform user to run the weather station\n(by default: user who launched the script, usually \"pi\" for default user on Raspberry Pi...)\n"
INSTALL_USER=$(ask_with_default "or press ENTER for default" "$(whoami)")

printf -- "\n"
PY_VENV=$(ask_with_default "Inform Python virtual environment path or press ENTER for default" "/usr/local/share/susanoo-py-venv")

# Test if the 'apt' package tool is available on running system:
package_tool_ok=true  # used later in install_python.sh
if ! command -v apt &> /dev/null
then
	printf -- "No 'apt' tool found.\n"
	printf -- "(all right if installing on unusual places such as Synology NAS,  etc...)\n"
	# Below variable package_tool_ok is used later in install_python.sh
	# shellcheck disable=SC2034
	package_tool_ok=false
fi

source "${SCRIPT_DIR}/install_python.sh"

# This script can be adapted to be executed from a Synology NAS to use it as web-server
# Pre-requisites:
# - activate ssh and connect as admin
# - add SynoCommunity as Package Sources (cf. https://synocommunity.com/ for more information).
# - add git package
# command should be 'synopkg install_from_server py3k', 'synopkg install_from_server MariaDB10'

printf -- "Installing MariaDB (database server and required Connector-C, etc...)...\n"
apt_install_or_skip mariadb-server
apt_install_or_skip libmariadb-dev

printf -- "\n\n*** APT installs for:... ***\n"
printf -- "- gpac to get 'MP4Box' command for webcam video captures\n"
# As detailed https://www.raspberrypi.org/documentation/usage/camera/raspicam/raspivid.md
printf -- "Installing multimedia...\n"
apt_install_or_skip gpac

## Also useful for developing from ssh command-line:
# sudo apt install vim vim-addon-manager

## mkdir -p ~/.vim/autoload ~/.vim/bundle
## curl -LSso ~/.vim/autoload/pathogen.cim https://tpo.pe/pathogen.vim
## echo "execute pathogen#infect()" >> ~/.vimrc
## echo "syntax on" >> ~/.vimrc
## echo "filetype plugin indent on" >> ~/.vimrc
## cd ~/.vim/bundle
## git clone https://github.com/klen/python-mode.git

printf -- "\n\n*** Create folder where images will be saved... ***\n"
mkdir -p "${HOME}/meteo/captures/"

# Executed on dev machine / includes GitHub project:
# mkdir -p ~/workspace/meteo/src/lib
# git clone https://github.com/adafruit/Adafruit_Python_BMP.git

printf -- "\n\n*** User to run web-server from... ***\n"

if id "${WEB_USER}" &>/dev/null; then
  printf -- "User \"%s\" already exists. No need to create it.\n" "${WEB_USER}"
else
  printf -- "\nUser \"%s\" does not exist but is required to run the web-server.\n" "${WEB_USER}"
  # Ask for confirmation before creating the user
  if ask_confirmation "Create user \"${WEB_USER}\" to run web-server from?" "yes"; then
    # The web server is exposed to the internet: its user gets the bare minimum. No password and no shell, so
    # nobody logs in as it (administrators use 'sudo -u ${WEB_USER} <command>'), and no extra group: never add
    # it to sudo, adm or (Synology NAS) administrators, which would hand a flaw in a page the whole machine.
    sudo adduser --disabled-password --gecos "" --shell /usr/sbin/nologin "${WEB_USER}" \
      || printf -- "ERROR! Does user \"%s\" already exist?!\n" "${WEB_USER}"
  else
    printf -- "User creation canceled.\n"
  fi
fi
for group in sudo adm administrators; do
  if id -nG "${WEB_USER}" 2> /dev/null | tr ' ' '\n' | grep -q -x "${group}"; then
    printf -- "WARNING: user \"%s\" is in group \"%s\": remove it (the web server must not have admin rights).\n" \
      "${WEB_USER}" "${group}"
  fi
done

# Raspberry Pi OS (Bookworm and later) creates private home folders (700): the web user could not reach the
# pages in this repository. Traverse right only (x): it cannot list the home folder, and the private files in it
# (config 600, ~/.ssh 700) stay private.
chmod o+x "${HOME}"

source "${SCRIPT_DIR}/bin/create_server_pages.sh" "${HOME}" "${WEB_USER}"

install_config_files

if ask_confirmation "Should we create database?" "yes"; then
  printf -- "Create database...\n"
  # One account per program, each with the least rights it needs: the collector can do anything, but only on
  # its database; the web server can only read it (bin/create_web_db_account.sh). Passwords are random and only
  # stored in the configs (mode 600): never a default password, and none on a command line (visible with 'ps').
  DB_NAME=$(collector_db_setting name)
  DB_NAME="${DB_NAME:-weather_station}"  # default of the Python code
  DB_USER=$(collector_db_setting user)
  DB_USER="${DB_USER:-${INSTALL_USER}}"
  DB_PASSWORD=$(collector_db_setting password)
  if [ -z "${DB_PASSWORD}" ] || [ "${DB_PASSWORD}" = "SetRandomPassword123" ]; then
    # Hexadecimal: nothing to escape in SQL, and no '%' (read as interpolation by Python's configparser)
    DB_PASSWORD=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    set_collector_db_password "${DB_PASSWORD}"
  fi
  printf -- "%s\n" \
    "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`;" \
    "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';" \
    "ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';" \
    "GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';" | sudo mariadb -u root
  unset DB_PASSWORD
  # To check users:        SELECT Host, User FROM mysql.user;
  sudo mariadb -u root "${DB_NAME}" < "${SCRIPT_DIR}/bin/db_initialization1_tables.sql"
  sudo mariadb -u root "${DB_NAME}" < "${SCRIPT_DIR}/bin/db_initialization2_data.sql"
  "${SCRIPT_DIR}/bin/db_migrate.sh"
  MYSQL="sudo mariadb -u root" PY_VENV="${PY_VENV}" "${SCRIPT_DIR}/bin/create_web_db_account.sh" "${INSTALL_USER}" "${WEB_USER}"

  printf -- "\n"
  printf -- "In order to use 'remote:' sensors (multiple weather stations/servers),\n"
  printf -- "you would need to configure your database to accept external connections.\n"
  printf -- "Check 'Activate remote access' for your database.\n"
  printf -- "For MySQL and MariaDB, comment parameter 'bind-address' that limit access to those IP\n"
  printf -- "in file below:\n"
  printf -- "\tcat /etc/mysql/my.cnf\n"
  printf -- "\n"
  # The master server reads the measures, sensors and captures of this station and marks the measures it copied
  # (raw_measures.synchronised): nothing more, and from its address only.
  printf -- "Appropriate user should also be created like (random password, also in the master's config):\n"
  printf -- "$ sudo mariadb -u root\n"
  printf -- "> CREATE USER 'remote_pi'@'192.168.0.{server-IP}' IDENTIFIED BY '<random password>';\n"
  printf -- "> GRANT SELECT ON %s.* TO 'remote_pi'@'192.168.0.{server-IP}';\n" "${DB_NAME}"
  printf -- "> GRANT UPDATE (synchronised) ON %s.raw_measures TO 'remote_pi'@'192.168.0.{server-IP}';\n" "${DB_NAME}"
  printf -- "\n"
fi


printf -- "\n\n*** Setup startup to launch Web server... ***\n"
# get location of '/etc/rc.d' for this system:
init_script_folder=$(get_init_script_folder)
if [ "${init_script_folder}" = "${UNKNOWN_LOCATION_ERROR}" ]; then
  printf -- "Initialization script folder not found. Please install manually.\n"
  read -r -p "Press Enter to continue..."
else
  if ask_confirmation "Should we make web server launched at startup?" "yes"; then
    # The init_script_folder exists
    # cp "${SCRIPT_DIR}/susanoo_WeatherStation_startWebServer.sh /usr/local/etc/rc.d/weatherStationWeb.sh
    # FIXME For some systems (like Synology NAS) scripts launched at startup are in folder /usr/local/etc/rc.d/
    # A copy owned by root, never a link to this repository: root runs it at boot, and the collector user (owner
    # of the repository) could otherwise run anything as root. Copy it again by hand after it changes.
    sudo cp "${SCRIPT_DIR}/bin/susanoo_WeatherStation_startWebServer.sh" "/etc/init.d/weatherStationWeb.sh"
    sudo chmod +x "/etc/init.d/weatherStationWeb.sh"
    sudo ln -s "/etc/init.d/weatherStationWeb.sh" "/etc/rc3.d/weatherStationWeb.sh"
    printf -- "Web server will be launched at restart.\n"
    read -r -p "Press Enter to continue..."
  fi
fi

cat << EOF


****************************************************************
*** INSTRUCTIONS TO MANUALLY FINISH THE INSTALLATION PROCESS ***
***  (all steps not yet automated but it should be easy...)  ***
****************************************************************

-
Add below line to crontab of user '\''${INSTALL_USER}'\'' by executing '\''crontab -e'\'':
* * * * *  ${PY_VENV}/bin/python3 ${HOME}/meteo/src/main/py/periodical_sensor_reading.py >> ${HOME}/susanoo-data.log 2>&1
-
If user can be specified in your OS (other than Raspbian):
* * * * *  ${INSTALL_USER}    ${PY_VENV}/bin/python3 "${HOME}/meteo/src/main/py/periodical_sensor_reading.py" >> "${HOME}/susanoo-data.log" 2>&1


As admin, add below lines at the end of /etc/rc.local, before last '\''exit 0'\'':
$ sudo vi /etc/rc.local
[...]
# Watchdog (only used for optional visible LED and possibility of shutting down the Raspberry Pi with button):
nohup -- ${PY_VENV}/bin/python3 -u ${HOME}/meteo/src/main/py/watchdog_gpio.py >> /var/log/watchdog_gpio.log 2>&1 &

# Camera trap:
sudo su - ${INSTALL_USER} --command \"nohup -- ${PY_VENV}/bin/python3 ${HOME}/meteo/src/main/py/video_capture_on_motion.py >> ${HOME}/meteo/video.log 2>&1\" &

# Webserver: (on a Synology NAS, it should be in /usr/local/etc/rc.d/weatherStationWeb.sh)
# (${WEB_USER} has no login shell: 'sudo -u', not 'su -')
sudo -H -u ${WEB_USER} sh -c "cd ${HOME}/../${WEB_USER}/public_html && nohup -- ${PY_VENV}/bin/python3 ${HOME}/meteo/src/main/py/server3.py >> ${HOME}/../${WEB_USER}/susanoo-web.log 2>&1" &


# Required to keep WiFi always on:
sleep 30 && sudo iw dev wlan0 set power_save off &

exit 0
-

Also, if willing to start without graphical GUI, this can be configured with 'sudo raspi-config'.
EOF

cd "${START_DIR}"
printf -- "\n\n\n%s script terminated successfully.\n" "${BASH_SOURCE[0]}"
exit 0

#!/usr/bin/env bash
set -e
# set -x

# Check if the script has received exactly 2 arguments
if [ "$#" -ne 2 ]; then
    printf -- "Error: This script requires 2 arguments.\n"
    printf -- "Usage: %s INSTALLER_HOME WEB_USER\n" "$0"
    printf -- "\n"
    printf -- "INSTALLER_HOME is the \${HOME} folder of the user where project is installed (eg.: /home/pi).\n"
    printf -- "WEB_USER is the user who run the web server (eg.: web)\n"
    exit 1
fi

L_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
L_HOME="$1"
L_WEB_USER="$2"

source "${L_SCRIPT_DIR}/helper_functions.sh"

# TODO Create a variable that replaces '${L_HOME}/../${L_WEB_USER}' by direct '${HOME_WEB_USER}' (without '..')
sudo mkdir --parents "${L_HOME}/../${L_WEB_USER}/public_html/html"
printf -- "Folder 'public_html' created in home of user '%s'\n" "${L_WEB_USER}"
# FIXME Should replace ${L_HOME}/meteo by ${PROJECT_FOLDER} (can be done from current script location)
create_link "${L_HOME}/meteo/src/main/py/public_html/captures.json.py" "${L_HOME}/../${L_WEB_USER}/public_html/captures.json"
create_link "${L_HOME}/meteo/src/main/py/public_html/index.html.py" "${L_HOME}/../${L_WEB_USER}/public_html/index.html"
create_link "${L_HOME}/meteo/src/main/py/public_html/favicon.ico" "${L_HOME}/../${L_WEB_USER}/public_html/favicon.ico"
create_link "${L_HOME}/meteo/src/main/py/public_html/graph.svg.py" "${L_HOME}/../${L_WEB_USER}/public_html/graph.svg"
create_link "${L_HOME}/meteo/src/main/py/public_html/measures.json.py" "${L_HOME}/../${L_WEB_USER}/public_html/measures.json"
create_link "${L_HOME}/meteo/src/main/py/public_html/html/capture.html" "${L_HOME}/../${L_WEB_USER}/public_html/html/capture.html"
create_link "${L_HOME}/meteo/src/main/py/public_html/html/health.html" "${L_HOME}/../${L_WEB_USER}/public_html/html/health.html"
create_link "${L_HOME}/meteo/src/main/py/public_html/html/graph.html" "${L_HOME}/../${L_WEB_USER}/public_html/html/graph.html"
create_link "${L_HOME}/meteo/src/main/py/public_html/html/graph.js" "${L_HOME}/../${L_WEB_USER}/public_html/html/graph.js"
create_link "${L_HOME}/meteo/src/main/py/public_html/disk.json.py" "${L_HOME}/../${L_WEB_USER}/public_html/disk.json"
create_link "${L_HOME}/meteo/src/main/py/public_html/html/favicon.ico" "${L_HOME}/../${L_WEB_USER}/public_html/html/favicon.ico"
create_link "${L_HOME}/meteo/src/main/py/public_html/html/favicon.svg" "${L_HOME}/../${L_WEB_USER}/public_html/html/favicon.svg"
create_link "${L_HOME}/meteo/src/main/py/public_html/html/script.js" "${L_HOME}/../${L_WEB_USER}/public_html/html/script.js"
create_link "${L_HOME}/meteo/src/main/py/public_html/html/styles.css" "${L_HOME}/../${L_WEB_USER}/public_html/html/styles.css"
create_link "${L_HOME}/meteo/src/main/py/public_html/html/undefined_4x3.png" "${L_HOME}/../${L_WEB_USER}/public_html/html/undefined_4x3.png"

create_link "${L_HOME}/meteo/captures" "${L_HOME}/../${L_WEB_USER}/public_html/"
sudo chmod --verbose 555 "${L_HOME}"/../"${L_WEB_USER}"/public_html/*.*
sudo chmod --verbose 444 "${L_HOME}"/../"${L_WEB_USER}"/public_html/html/*.*
printf -- "Links created in 'public_html' pointing to adequate folder '%s'\n" "${L_HOME}/meteo/..."

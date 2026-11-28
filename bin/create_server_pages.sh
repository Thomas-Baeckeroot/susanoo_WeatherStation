#!/usr/bin/env bash
set -e
# set -x

# Creates the web root of the web server (~WEB_USER/public_html/) with links to the pages of this repository.
# Run it as the data-collector user, owner of this repository; again after a 'git pull' that adds pages.
#
# Security model, the reasons for the owners and rights below:
# - The web server is exposed to the internet. It runs as WEB_USER, which can only read: its web root and the
#   code it runs belong to the collector user. A flaw in a page then cannot change any page, nor the collector's
#   code (run every minute by cron), nor anything else. So never make WEB_USER the owner of these files, nor a
#   member of an administrators / sudo group (on a Synology NAS, 'administrators' can write nearly every shared
#   folder and use sudo).
# - The collector user owns the code the links point to: owning the web root as well gives it no extra power, and
#   lets it add the links of new pages without root. Only the first creation of the folders needs sudo.
# - WEB_USER needs read access to the repository (pages, captures). On a Synology NAS, the home folders have
#   ACLs: give WEB_USER the Read permission on the repository folder (File Station > Properties > Permission,
#   applied to this folder, sub-folders and files). On Raspberry Pi OS (Bookworm and later), home folders are
#   private (700): 'chmod o+x' the collector's home so that WEB_USER can reach the repository; keep the
#   collector's config private (600, see create_web_db_account.sh).
# - The database: see create_web_db_account.sh (read-only account and private config for the web server).

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
L_WEB_ROOT="${L_HOME}/../${L_WEB_USER}/public_html"
L_PAGES="${L_HOME}/meteo/src/main/py/public_html"
L_OWNER=$(ls -ld "${L_HOME}/meteo" | awk '{print $3}')  # the collector user
if [ "$(id -un)" != "${L_OWNER}" ]; then
    printf -- "Run this script as '%s', owner of the repository (e.g.: sudo -u %s %s %s %s)\n" \
        "${L_OWNER}" "${L_OWNER}" "$0" "${L_HOME}" "${L_WEB_USER}"
    exit 1
fi
if [ ! -d "${L_WEB_ROOT}/html" ] || [ ! -w "${L_WEB_ROOT}" ] || [ ! -w "${L_WEB_ROOT}/html" ]; then
    # First time (or a web root created by an older version of this script, owned by root): needs sudo
    sudo mkdir -p "${L_WEB_ROOT}/html"
    sudo chown "${L_OWNER}" "${L_WEB_ROOT}" "${L_WEB_ROOT}/html"
    sudo chmod 755 "${L_WEB_ROOT}" "${L_WEB_ROOT}/html"
    printf -- "Folder '%s' created, owned by '%s', read-only for '%s'\n" "${L_WEB_ROOT}" "${L_OWNER}" "${L_WEB_USER}"
fi

create_link "${L_PAGES}/captures.json.py" "${L_WEB_ROOT}/captures.json"
create_link "${L_PAGES}/index.html.py" "${L_WEB_ROOT}/index.html"
create_link "${L_PAGES}/favicon.ico" "${L_WEB_ROOT}/favicon.ico"
create_link "${L_PAGES}/graph.svg.py" "${L_WEB_ROOT}/graph.svg"
create_link "${L_PAGES}/measures.json.py" "${L_WEB_ROOT}/measures.json"
create_link "${L_PAGES}/html/capture.html" "${L_WEB_ROOT}/html/capture.html"
create_link "${L_PAGES}/html/health.html" "${L_WEB_ROOT}/html/health.html"
create_link "${L_PAGES}/html/graph.html" "${L_WEB_ROOT}/html/graph.html"
create_link "${L_PAGES}/html/graph.js" "${L_WEB_ROOT}/html/graph.js"
create_link "${L_PAGES}/disk.json.py" "${L_WEB_ROOT}/disk.json"
create_link "${L_PAGES}/html/favicon.ico" "${L_WEB_ROOT}/html/favicon.ico"
create_link "${L_PAGES}/html/favicon.svg" "${L_WEB_ROOT}/html/favicon.svg"
create_link "${L_PAGES}/html/script.js" "${L_WEB_ROOT}/html/script.js"
create_link "${L_PAGES}/html/styles.css" "${L_WEB_ROOT}/html/styles.css"
create_link "${L_PAGES}/html/undefined_4x3.png" "${L_WEB_ROOT}/html/undefined_4x3.png"

create_link "${L_HOME}/meteo/captures" "${L_WEB_ROOT}/captures"
printf -- "Links created in '%s' pointing to adequate folder '%s'\n" "${L_WEB_ROOT}" "${L_HOME}/meteo/..."

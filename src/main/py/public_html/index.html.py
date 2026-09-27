#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import cgi
import db_module
import locale
import logging
import re
import sys
import time
import traceback
import urllib.parse

# from sensors_functions import iso_timestamp

HOME = db_module.get_home()
logging.basicConfig(
    filename=HOME + "/susanoo-web.log",  # = "/home/web/susanoo-web.log"
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8.8s%(name)-14s (%(process)5d) %(message)s')
log = logging.getLogger("index.html.py")

METEO_FOLDER = "/home/pi/meteo/"
CAPTURES_FOLDER = METEO_FOLDER + "captures/"

log.info("Start generating index.html")

form = cgi.FieldStorage()
locale.getdefaultlocale()
print("Content-type: text/html; charset=utf-8\n")

html = """<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="fr" lang="fr" dir="ltr">
<head>
    <title>Centrale météo St Benoît</title>
    <link rel="icon" type="image/svg+xml" href="html/favicon.svg">
</head>
<body style="background-color: lightsteelblue;">"""

two_day_ago = str(db_module.epoch_now() - 172800)

try:
    # Connect or Create DB File
    conn = db_module.get_conn()
    curs = conn.cursor()
    curs.execute(
        "SELECT  sensor, epochtimestamp, measure "
        "FROM    raw_measures AS raw1 "
        "WHERE   epochtimestamp > " + two_day_ago + ""
        "  AND   epochtimestamp ="
        "          ( SELECT  MAX(epochtimestamp)"
        "            FROM    raw_measures AS raw2"
        "            WHERE   epochtimestamp > " + two_day_ago + ""
        "              AND   raw1.sensor = raw2.sensor"
        "            GROUP BY sensor"
        "          ); ")
    values = curs.fetchall()
    last_values = {}
    for value in values:
        (sensor, max_epoch, measure) = value
        last_values[sensor.decode("utf-8")] = (max_epoch, measure)
    # TODO Upper request should be included as LEFT JOIN in below request
    # but when doing so, response took much more time...

    curs.execute(
        "SELECT  name, priority, sensor_label, unit, filepath_data "
        "FROM    sensors"
        "    LEFT JOIN captures ON sensors.name = captures.sensor_name "
        "ORDER BY priority DESC;")
    # SELECT name, priority, sensor_label, unit, epochtimestamp, measure
    # FROM   sensors
    #     LEFT JOIN raw_measures ON sensors.name = raw_measures.sensor
    #     AND epochtimestamp = ( SELECT  MAX(epochtimestamp)  FROM    raw_measures  WHERE   sensor = sensors.name );
    sensors = curs.fetchall()
    oldest_date = -1
    sensor_list =\
        "<table style=\"border: .15em solid black; border-collapse: collapse; background-color: white;\">\n" \
        "<tr style=\"border: .1em solid black; background-color: silver;\">\n" \
        "\t<th style=\"text-align: center;padding-right: 4em;\">Capteur</th>\n" \
        "\t<th style=\"text-align: center;\">valeur</th>\n" \
        "\t<td style=\"text-align: center;\">date</td>\n" \
        "\t<td></td>\n</tr>"
    camera_row = "<tr><td colspan=\"4\"><table style=\"width: 100%;text-align: center;\"><tr>"
    for sensor in sensors:
        (sensor_name, priority, sensor_label, unit, filepath_data) = sensor
        sensor_name = sensor_name.decode('ascii')

        if unit == "picture":  # Below 10, sensors are not displayed in top list (ie: pictures from camera)
            arguments = {'image': filepath_data}
            result = urllib.parse.urlencode(arguments, quote_via=urllib.parse.quote_plus)
            # TODO From index.html, link to the image should point to "html/capture.html" without further parameters
            # (letting capture.html showing the default date/time)

            # 'password=xyz&username=administrator'   # "image=" + urllib.parse.quote(filepath_data)
            # "<td><a href=\"/html/capture.html?image=" + urllib.parse.quote(filepath_data) + \
            camera_row = \
                camera_row + \
                "<td><a href=\"/html/capture.html?" + result + \
                "\"><img fetchpriority=\"high\" src=\"captures/" + filepath_data + \
                "\" width=\"360em\" height=\"270em\" style=\"background-color: lightgray\" /></a><br/>" + \
                sensor_label + "<br/>" + re.findall(r"(\d{4}-\d{2}-\d{2}.\d{2}-\d{2})", filepath_data)[0] + "</td>"

        elif priority > 10:
            if priority > 70:
                style_row = ""
                style_value = "font-weight: bold;"
            elif priority < 35:
                style_row = "color: Silver;"
                style_value = ""
            else:
                style_row = ""
                style_value = ""

            sensor_list = sensor_list + "<tr style=\"border: .069em solid lightgray;" + style_row + "\">"
            sensor_list = sensor_list + "\n\t<td style=\"padding-left: 1em;padding-right: 1em;\">" + sensor_label
            if sensor_name in last_values:
                (epochdate, value) = last_values[sensor_name]
                if oldest_date < epochdate:
                    oldest_date = epochdate
                # locale.getdefaultlocale()
                date_str = time.strftime('%-d/%m/%Y<br/>%H:%M:%S', time.localtime(epochdate))
                sensor_list =\
                    sensor_list + \
                    "</td>\n\t<td style=\"text-align: center;" + \
                    style_value + "\">" + str(value) + " " + unit + "</td>\n" + \
                    "\t<td style=\"text-align: center;font-size: x-small;\">" + \
                    date_str + \
                    "</td>\n\t<td style=\"text-align: center;\">" + \
                    "<a href=\"graph.svg?sensor=" + sensor_name + "&maxepoch=" + str(oldest_date) + \
                    "&width=980\">" + \
                    "<img data-src=\"graph.svg?sensor=" + sensor_name + "&maxepoch=" + str(oldest_date) + \
                    "&width=100\" style=\"width:6.25em;height:2.5em; background-color: whitesmoke\" />" + \
                    "</a><td></tr>\n"
            else:
                sensor_list = sensor_list + "</td>\n" \
                              + "<td style=\"text-align: center;padding-left: 1em;padding-right: 2em;" \
                              + style_value + "\">-</td>\n<td style=" \
                              + "\"padding-left: 1em;padding-right: 2em;font-size: x-small;text-align: center;\">-" \
                              + "</td>\n<td style=\"padding-left: 1em;padding-right: 2em;\"><td></tr>\n"

        # end of 'for sensor in sensors:'

    if oldest_date != -1:
        date_str = time.strftime('%A %-d %B - %H:%M', time.localtime(oldest_date))
        date_readings = "Dernier relevé le " + date_str
    else:
        date_readings = "Erreur de lecture de date!"

    sensor_list = \
        sensor_list + \
        "<tr style=\"border: .15em solid black;\">\n\t<td style=\"padding: 1em;\">" + \
        "<form action=\"index.html\">" + \
        "<input type=\"submit\" style=\"padding: 1.2em;\" value=\"Rafraichir\" />" + \
        "</form></td>\n\t<td style=\"padding: 1em;\" colspan=\"3\">" + date_readings + "</td></tr>" + camera_row + \
        "</tr></table></td></tr></table>"

    html = html + "<h3>Dernières valeurs:</h3>" + sensor_list

except Exception as err:
    html = html + "<br/>Exception: {0}<br/>".format(err)
    print("Exception: {0}".format(err), file=sys.stderr)
    traceback.print_exc(file=sys.stderr)

# Graphs are slow to generate and would take all the browser's connections: load them after the photos
html = html + """<script>
(function () {
    var photos = Array.prototype.filter.call(document.images, function (img) { return !img.dataset.src; });
    var pending = photos.filter(function (img) { return !img.complete; }).length;
    var started = false;
    function loadGraphs() {
        if (started) { return; }
        started = true;
        document.querySelectorAll("img[data-src]").forEach(function (img) { img.src = img.dataset.src; });
    }
    function photoDone() { if (--pending <= 0) { loadGraphs(); } }
    photos.forEach(function (img) {
        if (!img.complete) {
            img.addEventListener("load", photoDone);
            img.addEventListener("error", photoDone);
        }
    });
    if (pending === 0) { loadGraphs(); }
    setTimeout(loadGraphs, 5000);
})();
</script>"""
html = html + "</body></html>"
print(html)
log.info("Terminated generating index.html")

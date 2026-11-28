#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SVG graph of one sensor over the 24 hours up to 'maxepoch' (default: now):
    graph.svg?sensor=temp_ext[&maxepoch=<epoch>][&width=<px>]
Below 350 px wide (thumbnails of the index page): the line only, without text. The interactive graph page is
html/graph.html; this image stays for the index thumbnails and older links.
"""

import logging
import os
import time
import urllib.parse

import chart
import db_module

logging.basicConfig(
    filename=db_module.get_home() + "/susanoo-web.log",
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8.8s%(name)-14s (%(process)5d) %(message)s')
log = logging.getLogger("graph.svg.py")

SECONDS_IN_ONE_DAY = 86400
TINY_GRAPH_WIDTH = 350
# Longest query (s): on a cold cache, give up rather than pile up processes waiting on the disk
MAX_STATEMENT_SECONDS = 30


def int_parameter(parameters, name, default, low, high):
    try:
        return min(max(int(float(parameters.get(name, [default])[0])), low), high)
    except ValueError:
        return default


def main():
    started = time.monotonic()
    parameters = urllib.parse.parse_qs(os.environ.get("QUERY_STRING", ""))
    sensor = parameters.get("sensor", [""])[0]
    width = int_parameter(parameters, "width", 500, 50, 4000)
    height = int(width * 2 / 5)
    end = int_parameter(parameters, "maxepoch", int(time.time()), 0, 2 ** 31 - 1) + 1
    start = end - SECONDS_IN_ONE_DAY
    tiny = width < TINY_GRAPH_WIDTH
    # One bucket per pixel column at most (thumbnail: 100 px -> one point per 15 min)
    step = chart.bucket_step(start, end, width if tiny else width - 56)

    buckets = []
    try:
        conn = db_module.get_conn()
        try:
            curs = conn.cursor()
            curs.execute("SET SESSION max_statement_time = %s", (MAX_STATEMENT_SECONDS,))
            curs.execute("SELECT sensor_label, unit FROM sensors WHERE name = %s", (sensor,))
            row = curs.fetchone()
            buckets = chart.fetch_buckets(curs, sensor, start, end, step) if row else []
        finally:
            conn.close()
        label, unit = (row[0], row[1]) if row else (sensor, "")
        if tiny:
            svg = chart.sparkline_svg(buckets, start, end, step, width, height, title=label)
        else:
            svg = chart.chart_svg(buckets, start, end, step, width, height, unit=unit, title=label)
    except Exception:
        log.exception("Graph of sensor %r failed", sensor)
        svg = chart.no_data_svg(width, height, title="Erreur")

    # The URL holds the end of the period: data before it hardly changes (late remote sync aside)
    print("Content-Type: image/svg+xml; charset=utf-8")
    print("Cache-Control: max-age=300")
    print()
    print(svg)
    log.info("%s width=%d: %d buckets of %d s in %.2f s", sensor, width, len(buckets), step,
             time.monotonic() - started)


if __name__ == '__main__':
    main()

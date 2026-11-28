#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Measures of one sensor for the graph page html/graph.html, reduced to one bucket per pixel column:
    measures.json?sensor=temp_ext[&end=<epoch>][&span=<s> | &start=<epoch>][&points=<n>]
Default: the 24 hours up to now, the sensor of highest priority. Answers in JSON:
    {"sensor": {...}, "sensors": [{...}], "start", "end", "step", "sample", "first", "last": [epoch, value],
     "buckets": [[start of bucket, average, min, max, count], ...]}
or {"error": "..."} (always with HTTP 200: CGI scripts of http.server cannot set the status).
"""

import json
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
log = logging.getLogger("measures.json")

DEFAULT_PERIOD = 86400
MAX_PERIOD = 20 * 366 * 86400
DEFAULT_POINTS = 800
# Longest query (s): a long period on a cold cache must not keep the database busy after the visitor left
MAX_STATEMENT_SECONDS = 30


def int_parameter(parameters, name, default, low, high):
    try:
        return min(max(int(float(parameters.get(name, [default])[0])), low), high)
    except ValueError:
        return default


def rounded(value, decimals):
    return None if value is None else round(value, decimals)


def answer(document):
    print("Content-Type: application/json; charset=utf-8")
    print("Cache-Control: no-cache")
    print()
    print(json.dumps(document, ensure_ascii=False, separators=(",", ":")))


def measures(parameters):
    now = int(time.time())
    end = int_parameter(parameters, "end", now + 60, 0, 2 ** 31 - 1)
    span = int_parameter(parameters, "span", DEFAULT_PERIOD, 60, MAX_PERIOD)
    start = int_parameter(parameters, "start", end - span, max(0, end - MAX_PERIOD), end - 60)
    points = int_parameter(parameters, "points", DEFAULT_POINTS, 10, 3000)
    step = chart.bucket_step(start, end, points)
    wanted = parameters.get("sensor", [""])[0]

    conn = db_module.get_conn()
    try:
        curs = conn.cursor()
        curs.execute("SET SESSION max_statement_time = %s", (MAX_STATEMENT_SECONDS,))
        curs.execute("SELECT name, sensor_label, unit, decimals, cumulative FROM sensors"
                     " WHERE priority > 10 AND (unit IS NULL OR unit <> 'picture') ORDER BY priority DESC")
        sensors = [{"name": name.decode("ascii"), "label": label, "unit": unit or "",
                    "decimals": 2 if decimals is None else int(decimals), "cumulative": bool(cumulative)}
                   for name, label, unit, decimals, cumulative in curs.fetchall()]
        sensor = next((s for s in sensors if s["name"] == wanted), None) if wanted else \
            (sensors[0] if sensors else None)
        if sensor is None:
            return {"error": "Capteur inconnu : %s" % wanted, "sensors": sensors}
        name = sensor["name"]
        curs.execute("SELECT MIN(epochtimestamp) FROM raw_measures WHERE sensor = %s", (name,))
        first = curs.fetchone()[0]
        curs.execute("SELECT epochtimestamp, measure FROM raw_measures WHERE sensor = %s"
                     " ORDER BY epochtimestamp DESC LIMIT 1", (name,))
        last = curs.fetchone()
        sql_started = time.monotonic()
        buckets = chart.fetch_buckets(curs, name, start, end, step)
        sql_seconds = time.monotonic() - sql_started
    finally:
        conn.close()

    decimals = sensor["decimals"] + 1
    log.info("%s %d s / %d s: %d buckets, SQL in %.2f s", name, end - start, step, len(buckets), sql_seconds)
    return {
        "sensor": sensor,
        "sensors": sensors,
        "start": start,
        "end": end,
        "step": step,
        "sample": chart.sampling(step),
        "now": now,
        "first": first,
        "last": [last[0], rounded(last[1], decimals)] if last else None,
        "buckets": [[epoch, rounded(average, decimals), rounded(low, decimals), rounded(high, decimals), count]
                    for epoch, average, low, high, count in buckets],
    }


def main():
    parameters = urllib.parse.parse_qs(os.environ.get("QUERY_STRING", ""))
    try:
        document = measures(parameters)
    except Exception as error:
        log.exception("measures.json failed for %r", parameters)
        timeout = "max_statement_time" in str(error) or "1969" in str(error)
        document = {"error": "Requête trop longue, essayez une période plus courte" if timeout
                    else "Erreur du serveur : %s" % error}
    answer(document)


if __name__ == '__main__':
    main()

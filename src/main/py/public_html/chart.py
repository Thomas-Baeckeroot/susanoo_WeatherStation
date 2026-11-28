# -*- coding: utf-8 -*-
"""
Measures of one sensor over a time range, reduced in SQL to one bucket (average, min, max) per pixel column,
and their rendering as SVG. Shared by graph.svg.py (images) and measures.json.py (data of html/graph.html).

Kept compatible with Python 3.7 (system python3 of the Raspberry Pis) and free of third-party modules.
"""

import math
import time

# Bucket durations, from the measuring period (a minute), that keep buckets on round clock times (all divide a
# day), then whole days. Nothing between 3 h and 1 day: such buckets alternate day and night, and their
# averages would zigzag
NICE_STEPS = (60, 120, 180, 300, 600, 900, 1200, 1800, 3600, 7200, 10800, 86400)
# A line is broken between two buckets further apart than this (and 3 buckets): a sensor or a sync outage
GAP_SECONDS = 600
# Longer periods are read in chunks: past about a month, MariaDB reads every index entry of the sensor
# ('ref' access) instead of the time range, e.g. 9 s instead of 4.7 s for a year on a Pi 4
CHUNK_SECONDS = 30 * 86400
# Buckets of a day or more only use one measure per SAMPLE_SECONDS (about 10 times fewer rows to read):
# enough for daily average, min and max. Measures are taken at any second of their minute
SAMPLE_SECONDS = 600

# Series colours: same palette as html/graph.js
LINE_COLOUR = "#1f5fa8"
FILL_COLOUR = "#1f5fa8"
GRID_COLOUR = "#d8dde6"
TEXT_COLOUR = "#4a5262"


def bucket_step(start, end, points):
    """Duration (s) of a bucket so that [start, end) is drawn with at most about `points` buckets."""
    wanted = (end - start) / float(max(points, 1))
    for step in NICE_STEPS:
        if step >= wanted:
            return step
    return int(math.ceil(wanted / 86400.0)) * 86400


def gap_threshold(step):
    return max(3 * step, GAP_SECONDS)


def sampling(step):
    """Seconds between the measures used for buckets of `step` seconds: None when all are used."""
    return SAMPLE_SECONDS if step >= 86400 else None


def fetch_buckets(curs, sensor, start, end, step):
    """[(bucket start, average, min, max, count)] of the measures of `sensor` in [start, end), in time order.

    Buckets are aligned on multiples of `step` since the epoch; empty buckets are absent. Grouping also
    merges the duplicate rows that the remote sync may insert. See CHUNK_SECONDS and sampling()."""
    sample = sampling(step)
    sql = ("SELECT   epochtimestamp DIV %s AS bucket, AVG(measure), MIN(measure), MAX(measure), COUNT(measure)"
           " FROM    raw_measures"
           " WHERE   sensor = %s AND epochtimestamp >= %s AND epochtimestamp < %s"
           # '%%': pymysql formats the query with '%' (the parameters)
           + (" AND epochtimestamp %% " + str(sample) + " < 60" if sample else "") +
           " GROUP BY bucket"
           " ORDER BY bucket")
    # Chunks are whole buckets: no bucket is split between two queries
    chunk = max(step, CHUNK_SECONDS // step * step)
    buckets = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start // step * step + chunk, end)
        curs.execute(sql, (step, sensor, chunk_start, chunk_end))
        buckets.extend((int(bucket) * step, float(average), float(low), float(high), int(count))
                       for bucket, average, low, high, count in curs.fetchall() if count)
        chunk_start = chunk_end
    return buckets


def bucket_time(bucket, step, start, end):
    """Time at which a bucket is drawn: its middle, kept inside [start, end] (partial first / last bucket)."""
    return min(max(bucket[0] + step / 2.0, start), end)


def segments(buckets, step):
    """Splits buckets into runs without gaps, each drawn as one line."""
    runs = []
    previous = None
    threshold = gap_threshold(step)
    for bucket in buckets:
        if previous is None or bucket[0] - previous[0] > threshold:
            runs.append([])
        runs[-1].append(bucket)
        previous = bucket
    return runs


def nice_ticks(low, high, count=5):
    """About `count` round values covering [low, high]: (ticks, step)."""
    if high <= low:
        low, high = low - 0.5, high + 0.5
    raw = (high - low) / float(max(count, 1))
    magnitude = 10 ** math.floor(math.log10(raw))
    step = magnitude * 10
    for factor in (1, 2, 2.5, 5, 10):
        if factor * magnitude >= raw:
            step = factor * magnitude
            break
    first = int(math.floor(low / step + 1e-9))
    last = int(math.ceil(high / step - 1e-9))
    return [round(k * step, 10) for k in range(first, last + 1)], step


def value_range(buckets):
    low = min(bucket[2] for bucket in buckets)
    high = max(bucket[3] for bucket in buckets)
    if high - low < 1e-9:
        # Flat line: centred, with a visible scale
        margin = max(abs(low) * 0.01, 0.5)
        low, high = low - margin, high + margin
    return low, high


def format_number(value, step):
    decimals = 0 if step >= 1 else int(math.ceil(-math.log10(step) - 1e-9))
    text = "%.*f" % (decimals, value)
    return "0" if text in ("-0", "-0.0", "-0.00") else text


def escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def svg_document(width, height, body, title=None):
    title_element = "<title>%s</title>" % escape(title) if title else ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d"'
            ' font-family="sans-serif">%s%s</svg>' % (width, height, width, height, title_element, body))


def no_data_svg(width, height, title=None):
    font_size = max(8, min(14, height // 3))
    body = ('<text x="%d" y="%d" text-anchor="middle" dominant-baseline="middle" font-size="%d" fill="%s">'
            '%s</text>' % (width // 2, height // 2, font_size, TEXT_COLOUR,
                           "—" if width < 200 else "Pas de mesure sur cette période"))
    return svg_document(width, height, body, title)


def sparkline_svg(buckets, start, end, step, width, height, title=None):
    """Thumbnail of the index page: the average line over a light area, the last value marked, no text."""
    if not buckets:
        return no_data_svg(width, height, title)
    low, high = value_range(buckets)
    pad = 2.0
    span = float(end - start)

    def x(bucket):
        return (bucket_time(bucket, step, start, end) - start) * width / span

    def y(value):
        return pad + (high - value) * (height - 2 * pad) / (high - low)

    parts = []
    if low < 0 < high:
        parts.append('<line x1="0" x2="%d" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="0.8"'
                     ' stroke-dasharray="2,2"/>' % (width, y(0), y(0), GRID_COLOUR))
    for run in segments(buckets, step):
        points = " ".join("%.1f,%.1f" % (x(bucket), y(bucket[1])) for bucket in run)
        if len(run) > 1:
            parts.append('<polygon points="%.1f,%d %s %.1f,%d" fill="%s" fill-opacity="0.18"/>'
                         % (x(run[0]), height, points, x(run[-1]), height, FILL_COLOUR))
        parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.3"'
                     ' stroke-linejoin="round"/>' % (points, LINE_COLOUR))
    last = buckets[-1]
    parts.append('<circle cx="%.1f" cy="%.1f" r="1.8" fill="%s"/>' % (x(last), y(last[1]), LINE_COLOUR))
    return svg_document(width, height, "".join(parts), title)


def time_ticks(start, end, max_ticks):
    """[(epoch, label)] on round local times (hours, then midnights) inside [start, end)."""
    hour_choices = (1, 2, 3, 6, 12, 24)
    hours = next((h for h in hour_choices if (end - start) / (h * 3600.0) <= max_ticks), None)
    ticks = []
    if hours is not None:
        # Local hours fall on whole UTC hours (time zones of the stations: CET / CEST)
        epoch = start - start % 3600 + 3600
        while epoch < end:
            local = time.localtime(epoch)
            if local.tm_min == 0 and local.tm_hour % hours == 0:
                if local.tm_hour == 0:
                    ticks.append((epoch, "%d/%02d" % (local.tm_mday, local.tm_mon)))
                else:
                    ticks.append((epoch, "%dh" % local.tm_hour))
            epoch += 3600
        return ticks
    days = int(math.ceil((end - start) / 86400.0 / max_ticks))
    epoch = start - start % 3600 + 3600
    while epoch < end:
        local = time.localtime(epoch)
        if local.tm_hour == 0 and local.tm_min == 0 and local.tm_yday % days == 0:
            ticks.append((epoch, "%d/%02d" % (local.tm_mday, local.tm_mon)))
            epoch += 86400 - 7200  # next local midnight is ~1 day later (DST: 23 or 25 h)
        epoch += 3600
    return ticks


def chart_svg(buckets, start, end, step, width, height, unit="", title=None):
    """Graph with axes: min-max band, average line, value and time scales (local time)."""
    if not buckets:
        return no_data_svg(width, height, title)
    left, right, top, bottom = 46, 10, 8, 20
    plot_width, plot_height = width - left - right, height - top - bottom
    y_ticks, y_step = nice_ticks(*value_range(buckets), count=max(2, plot_height // 40))
    low, high = y_ticks[0], y_ticks[-1]
    span = float(end - start)

    def x_of(epoch):
        return left + (epoch - start) * plot_width / span

    def x(bucket):
        return x_of(bucket_time(bucket, step, start, end))

    def y(value):
        return top + (high - value) * plot_height / (high - low)

    parts = ['<rect x="%d" y="%d" width="%d" height="%d" fill="#fff"/>' % (left, top, plot_width, plot_height)]
    for value in y_ticks:
        parts.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>'
                     % (left, left + plot_width, y(value), y(value), GRID_COLOUR))
        parts.append('<text x="%d" y="%.1f" text-anchor="end" dominant-baseline="middle" font-size="11"'
                     ' fill="%s">%s</text>' % (left - 4, y(value), TEXT_COLOUR, format_number(value, y_step)))
    for epoch, label in time_ticks(start, end, max(2, plot_width // 60)):
        parts.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" stroke="%s" stroke-width="1"/>'
                     % (x_of(epoch), x_of(epoch), top, top + plot_height, GRID_COLOUR))
        parts.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="11" fill="%s">%s</text>'
                     % (x_of(epoch), height - 5, TEXT_COLOUR, escape(label)))
    if unit:
        # Bottom left corner, the only place free of value and time labels
        parts.append('<text x="4" y="%d" font-size="11" fill="%s">%s</text>' % (height - 5, TEXT_COLOUR, escape(unit)))
    for run in segments(buckets, step):
        band = " ".join("%.1f,%.1f" % (x(b), y(b[3])) for b in run) + " " + \
               " ".join("%.1f,%.1f" % (x(b), y(b[2])) for b in reversed(run))
        parts.append('<polygon points="%s" fill="%s" fill-opacity="0.2"/>' % (band, FILL_COLOUR))
        parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.5" stroke-linejoin="round"/>'
                     % (" ".join("%.1f,%.1f" % (x(b), y(b[1])) for b in run), LINE_COLOUR))
    return svg_document(width, height, "".join(parts), title)

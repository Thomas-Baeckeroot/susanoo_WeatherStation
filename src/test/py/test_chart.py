"""Tests of the graphs: chart.py (buckets, scales, SVG) and the CGI scripts graph.svg.py and measures.json.py.

The database is replaced by a fake cursor: no MariaDB nor pymysql needed (the SQL itself is MariaDB-specific).
Run from the repository root with any python3 >= 3.7:
    python3 -m unittest discover -s src/test/py -p test_chart.py -v
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ElementTree

PUBLIC_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "main", "py", "public_html")
sys.path.insert(0, os.path.abspath(PUBLIC_HTML))

import chart  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
DAY = 86400


def parse_svg(text):
    root = ElementTree.fromstring(text)
    assert root.tag == SVG + "svg", root.tag
    return root


def buckets_every(step, start, count, value=lambda i: float(i)):
    return [(start + i * step, value(i), value(i) - 1, value(i) + 1, 1) for i in range(count)]


class BucketStepTest(unittest.TestCase):

    def test_one_bucket_per_pixel_column_at_most(self):
        self.assertEqual(900, chart.bucket_step(0, DAY, 100))  # index thumbnail: one point per 15 min
        self.assertEqual(120, chart.bucket_step(0, DAY, 720))
        self.assertEqual(60, chart.bucket_step(0, DAY, 3000))  # never below the measuring period

    def test_long_periods_use_whole_days(self):
        # Buckets of 6 or 12 h would alternate day and night
        self.assertEqual(DAY, chart.bucket_step(0, 365 * DAY, 1200))
        self.assertEqual(2 * DAY, chart.bucket_step(0, 365 * DAY, 300))
        self.assertEqual(10800, chart.bucket_step(0, 30 * DAY, 300))


class SegmentsTest(unittest.TestCase):

    def test_line_broken_over_gaps_only(self):
        buckets = buckets_every(60, 0, 5) + buckets_every(60, 3600, 3)
        runs = chart.segments(buckets, 60)
        self.assertEqual([5, 3], [len(run) for run in runs])

    def test_short_gap_kept_continuous(self):
        # A missing minute or two (e.g. the daily reboot of a Pi) does not break the line
        buckets = [(0, 1.0, 1.0, 1.0, 1), (60, 1.0, 1.0, 1.0, 1), (300, 1.0, 1.0, 1.0, 1)]
        self.assertEqual(1, len(chart.segments(buckets, 60)))

    def test_gap_threshold_grows_with_buckets(self):
        self.assertEqual(3 * DAY, chart.gap_threshold(DAY))


class NiceTicksTest(unittest.TestCase):

    def test_round_values_covering_the_range(self):
        ticks, step = chart.nice_ticks(10.2, 21.7, 5)
        self.assertIn(step, (2, 2.5, 5))
        self.assertLessEqual(ticks[0], 10.2)
        self.assertGreaterEqual(ticks[-1], 21.7)
        for tick in ticks:
            self.assertAlmostEqual(0, (tick / step) - round(tick / step))

    def test_flat_values_still_get_a_scale(self):
        ticks, _ = chart.nice_ticks(3.3, 3.3, 5)
        self.assertLess(ticks[0], 3.3)
        self.assertGreater(ticks[-1], 3.3)

    def test_labels_without_spurious_decimals(self):
        self.assertEqual("1013", chart.format_number(1013.0, 1))
        self.assertEqual("2.5", chart.format_number(2.5, 0.5))
        self.assertEqual("0", chart.format_number(-0.0001, 1))


class FetchBucketsTest(unittest.TestCase):

    def test_query_parameters_and_bucket_times(self):
        executed = []

        class Cursor:
            def execute(self, sql, params):
                executed.append((sql, params))

            def fetchall(self):
                return [(1000, 10.5, 10.0, 11.0, 3), (1001, None, None, None, 0)]

        result = chart.fetch_buckets(Cursor(), "temp_ext", 900000, 986400, 900)
        sql, params = executed[0]
        self.assertEqual((900, "temp_ext", 900000, 986400), params)  # parameterised: no SQL injection
        self.assertNotIn("temp_ext", sql)
        self.assertEqual([(900000, 10.5, 10.0, 11.0, 3)], result)  # empty buckets dropped

    def test_long_periods_in_sampled_chunks_of_whole_buckets(self):
        executed = []

        class Cursor:
            def execute(self, sql, params):
                sql % tuple(repr(param) for param in params)  # pymysql-style formatting must work
                executed.append((sql, params))

            def fetchall(self):
                return []

        start, end = 1700000000, 1700000000 + 365 * DAY
        chart.fetch_buckets(Cursor(), "temp_ext", start, end, DAY)
        self.assertEqual(13, len(executed))
        bounds = [params[2:] for _, params in executed]
        self.assertEqual(start, bounds[0][0])
        self.assertEqual(end, bounds[-1][1])
        for (_, previous_end), (next_start, _) in zip(bounds, bounds[1:]):
            self.assertEqual(previous_end, next_start)  # contiguous
            self.assertEqual(0, next_start % DAY)  # on bucket boundaries
        self.assertIn("% 600 < 60", executed[0][0] % tuple(repr(p) for p in executed[0][1]))
        executed.clear()
        chart.fetch_buckets(Cursor(), "temp_ext", start, start + DAY, 120)
        self.assertEqual(1, len(executed))
        self.assertNotIn("600", executed[0][0])  # short periods: every measure


class SvgTest(unittest.TestCase):

    def test_sparkline_is_small_valid_svg(self):
        start = 1764000000
        buckets = buckets_every(900, start, 96, lambda i: (i % 24) - 5.0)
        svg = chart.sparkline_svg(buckets, start, start + DAY, 900, 100, 40, title="Température <ext>")
        root = parse_svg(svg)
        self.assertEqual("100", root.get("width"))
        self.assertIsNotNone(root.find(SVG + "polyline"))
        self.assertIsNone(root.find(SVG + "text"))  # no text on thumbnails
        self.assertLess(len(svg), 5000)

    def test_chart_has_scales_and_survives_flat_values(self):
        start = 1764000000
        buckets = buckets_every(120, start, 720, lambda i: 3.3)
        root = parse_svg(chart.chart_svg(buckets, start, start + DAY, 120, 980, 392, unit="V"))
        labels = [text.text for text in root.iter(SVG + "text")]
        self.assertIn("V", labels)
        self.assertTrue(any(label.endswith("h") for label in labels), labels)  # hours on the time scale

    def test_no_data(self):
        for function in (chart.sparkline_svg, chart.chart_svg):
            root = parse_svg(function([], 0, DAY, 900, 500, 200))
            self.assertEqual(1, len(list(root.iter(SVG + "text"))))

    def test_time_ticks_inside_the_period(self):
        start = 1764000000
        ticks = chart.time_ticks(start, start + DAY, 10)
        self.assertTrue(4 <= len(ticks) <= 10, ticks)
        self.assertTrue(all(start < epoch < start + DAY for epoch, _ in ticks))
        week = chart.time_ticks(start, start + 7 * DAY, 8)
        self.assertTrue(all("/" in label for _, label in week), week)  # dates only


class FakeCursor:
    """Answers the few queries of graph.svg.py and measures.json.py."""
    SENSORS = [(b"temp_ext", "Température", "°C", 1, 0), (b"pressure", "Pression", "hPa", 1, 0)]

    def __init__(self, log):
        self.log = log
        self.rows = []

    def execute(self, sql, params=()):
        sql % tuple(repr(param) for param in params)  # as pymysql does: a lone '%' in the SQL would fail
        sql = " ".join(sql.split())
        self.log.append((sql, params))
        if sql.startswith("SET SESSION"):
            self.rows = []
        elif sql.startswith("SELECT name, sensor_label"):
            self.rows = self.SENSORS
        elif sql.startswith("SELECT sensor_label, unit FROM sensors"):
            self.rows = [(s[1], s[2]) for s in self.SENSORS if s[0].decode() == params[0]]
        elif sql.startswith("SELECT MIN(epochtimestamp)"):
            self.rows = [(1500000000,)]
        elif sql.startswith("SELECT epochtimestamp, measure"):
            self.rows = [(1764000000, 12.345678)]
        elif "DIV" in sql:
            step, _, start, end = params
            self.rows = [(epoch // step, 12.345678, 11.0, 13.0, 15) for epoch in range(start, end, step)]
        else:
            raise AssertionError("unexpected SQL: " + sql)

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class CgiScriptsTest(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="chart-test-")
        self.queries = []
        fake_db = types.ModuleType("db_module")
        fake_db.get_home = lambda: self.home
        fake_db.get_conn = lambda host=None: types.SimpleNamespace(
            cursor=lambda: FakeCursor(self.queries), close=lambda: None)
        self.saved_db_module = sys.modules.get("db_module")
        sys.modules["db_module"] = fake_db

    def tearDown(self):
        if self.saved_db_module is None:
            sys.modules.pop("db_module", None)
        else:
            sys.modules["db_module"] = self.saved_db_module
        os.environ.pop("QUERY_STRING", None)
        import shutil
        shutil.rmtree(self.home, ignore_errors=True)

    def run_script(self, name, query):
        spec = importlib.util.spec_from_file_location(name.replace(".", "_"), os.path.join(PUBLIC_HTML, name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        os.environ["QUERY_STRING"] = query
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            module.main()
        head, _, body = output.getvalue().partition("\n\n")
        return head, body

    def test_measures_json(self):
        head, body = self.run_script("measures.json", "sensor=pressure&end=1764086400&span=86400&points=96")
        self.assertIn("Content-Type: application/json", head)
        data = json.loads(body)
        self.assertEqual("pressure", data["sensor"]["name"])
        self.assertEqual(["temp_ext", "pressure"], [s["name"] for s in data["sensors"]])
        self.assertEqual(900, data["step"])
        self.assertEqual(1764000000, data["start"])
        self.assertEqual(96, len(data["buckets"]))
        self.assertEqual([1764000000, 12.35, 11.0, 13.0, 15], data["buckets"][0])  # decimals + 1
        self.assertEqual([1764000000, 12.35], data["last"])

    def test_measures_json_defaults_and_unknown_sensor(self):
        data = json.loads(self.run_script("measures.json", "")[1])
        self.assertEqual("temp_ext", data["sensor"]["name"])  # highest priority
        self.assertEqual(86400, data["end"] - data["start"])
        data = json.loads(self.run_script("measures.json", "sensor=nope'%20OR%201=1")[1])
        self.assertIn("error", data)
        self.assertEqual(2, len(data["sensors"]))

    def test_measures_json_clamps_parameters(self):
        data = json.loads(self.run_script("measures.json", "end=1764086400&span=abc&points=999999")[1])
        self.assertEqual(86400, data["end"] - data["start"])
        self.assertEqual(60, data["step"])  # 3000 points at most

    def test_graph_svg_thumbnail_and_large(self):
        head, body = self.run_script("graph.svg", "sensor=temp_ext&maxepoch=1764086399&width=100")
        self.assertIn("Content-Type: image/svg+xml", head)
        self.assertIsNone(parse_svg(body).find(SVG + "text"))
        _, body = self.run_script("graph.svg", "sensor=temp_ext&maxepoch=1764086399&width=980")
        self.assertTrue(list(parse_svg(body).iter(SVG + "text")))
        self.assertIn(("SET SESSION max_statement_time = %s", (30,)), self.queries)  # time limit

    def test_graph_svg_unknown_sensor_does_not_query_measures(self):
        _, body = self.run_script("graph.svg", "sensor=x'%3B%20DROP%20TABLE%20sensors&width=100")
        parse_svg(body)
        self.assertFalse(any("DIV" in sql for sql, _ in self.queries))


if __name__ == "__main__":
    unittest.main()

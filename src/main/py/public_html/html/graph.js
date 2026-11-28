"use strict";
// Graph page (graph.html): loads the measures of one sensor from /measures.json and draws them in SVG.
// URL: graph.html?sensor=temp_ext[&span=<seconds>][&end=<epoch>] (no 'end': up to now).
// Times are shown in the browser's time zone.

const DEFAULT_SPAN = 86400;
const MIN_SPAN = 3600;
const MAX_SPAN = 20 * 366 * 86400;
const GAP_SECONDS = 600;  // as in chart.py: the line is broken over longer gaps (and over 3 buckets)
const REFRESH_MS = 120000;  // reload of the graph "up to now" while the page is visible
const STALE_SECONDS = 3600;  // last measure older than this: flagged
const MARGIN = {left: 52, right: 14, top: 12, bottom: 30};
const COLOURS = {line: "#1f5fa8", grid: "#e3e7ee", gridMajor: "#b8c0cc", zero: "#8f99ab", text: "#5b6475"};
const DAYS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const TICK_STEPS = [["h", 1], ["h", 2], ["h", 3], ["h", 6], ["h", 12], ["d", 1], ["d", 2], ["d", 7], ["d", 14],
    ["m", 1], ["m", 2], ["m", 3], ["m", 6], ["y", 1], ["y", 2], ["y", 5]];
const UNIT_SECONDS = {h: 3600, d: 86400, m: 30.44 * 86400, y: 365.25 * 86400};

const state = {
    sensor: null,
    span: DEFAULT_SPAN,
    end: null,  // null: up to now
    data: null,
    points: 0,  // number of buckets asked for: the plot width at loading time
    request: null,  // AbortController of the request in progress
    loadedAt: 0,
    geometry: null,  // scales of the last drawing, for the cursor
    drag: null,  // start (x) of a mouse selection, for zooming
};

const $ = (id) => document.getElementById(id);

function pad(number) {
    return String(number).padStart(2, "0");
}

function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function nowEpoch() {
    return Math.floor(Date.now() / 1000);
}

// ---- Formatting ----

function formatDate(date) {
    const text = DAYS[date.getDay()] + " " + date.getDate() + "/" + pad(date.getMonth() + 1);
    return date.getFullYear() === new Date().getFullYear() ? text : text + "/" + date.getFullYear();
}

function formatTime(date) {
    return date.getHours() + ":" + pad(date.getMinutes());
}

function formatDateTime(epoch) {
    const date = new Date(epoch * 1000);
    return formatDate(date) + " " + formatTime(date);
}

function formatValue(value, sensor) {
    const text = value.toFixed(sensor.decimals);
    return (/^-0(\.0+)?$/.test(text) ? text.substring(1) : text) + (sensor.unit ? " " + sensor.unit : "");
}

function formatTick(value, step) {
    const decimals = step >= 1 ? 0 : Math.ceil(-Math.log10(step) - 1e-9);
    const text = value.toFixed(decimals);
    return /^-0(\.0+)?$/.test(text) ? text.substring(1) : text;
}

// Period covered by one bucket, as shown in the cursor's label
function formatBucket(bucket, step) {
    const start = new Date(bucket[0] * 1000);
    if (step <= 60) {
        return formatDate(start) + " " + formatTime(start);
    }
    if (step >= 86400) {
        return step === 86400 ? formatDate(start) : formatDate(start) + " → " + formatDate(new Date((bucket[0] + step) * 1000));
    }
    return formatDate(start) + " " + formatTime(start) + "–" + formatTime(new Date((bucket[0] + step) * 1000));
}

// ---- Scales ----

function niceTicks(low, high, count) {
    if (high - low < 1e-9) {
        const margin = Math.max(Math.abs(low) * 0.01, 0.5);
        low -= margin;
        high += margin;
    }
    const raw = (high - low) / Math.max(count, 1);
    const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
    const factor = [1, 2, 2.5, 5, 10].find((f) => f * magnitude >= raw);
    const step = factor * magnitude;
    const ticks = [];
    for (let k = Math.floor(low / step + 1e-9); k <= Math.ceil(high / step - 1e-9); k++) {
        ticks.push(Math.round(k * step * 1e10) / 1e10);
    }
    return {ticks, step};
}

function tickAligned(date, unit, n) {
    if (unit === "h") {
        return date.getMinutes() === 0 && date.getHours() % n === 0;
    }
    if (unit === "d") {
        // Days since Monday 5 January 1970 (local): weeks start on Monday
        const days = Math.round((date - new Date(1970, 0, 5)) / 86400000);
        return n === 1 || (n === 2 ? days % 2 === 0 : days % n === 0);
    }
    if (unit === "m") {
        return date.getMonth() % n === 0;
    }
    return date.getFullYear() % n === 0;
}

function tickLabel(date, unit, n, span) {
    if (unit === "h") {
        return date.getHours() === 0 ? {label: formatDate(date), major: true} : {label: date.getHours() + "h", major: false};
    }
    if (unit === "d") {
        const label = n === 1 && span <= 10 * 86400 ? formatDate(date) : date.getDate() + "/" + pad(date.getMonth() + 1);
        return {label, major: date.getDate() === 1};
    }
    if (unit === "m") {
        return date.getMonth() === 0 ? {label: MONTHS[0] + " " + date.getFullYear(), major: true} :
            {label: MONTHS[date.getMonth()], major: false};
    }
    return {label: String(date.getFullYear()), major: true};
}

// Ticks on round local times: hours, days (weeks from Monday), months or years, at most about maxTicks
function timeTicks(start, end, maxTicks) {
    const span = end - start;
    const [unit, n] = TICK_STEPS.find(([u, k]) => span / (k * UNIT_SECONDS[u]) <= maxTicks) ||
        TICK_STEPS[TICK_STEPS.length - 1];
    const date = new Date(start * 1000);
    date.setMinutes(0, 0, 0);
    if (unit !== "h") {
        date.setHours(0);
    }
    if (unit === "m" || unit === "y") {
        date.setDate(1);
    }
    if (unit === "y") {
        date.setMonth(0);
    }
    const ticks = [];
    for (let guard = 0; guard < 5000; guard++) {
        const epoch = date.getTime() / 1000;
        if (epoch >= end) {
            break;
        }
        if (epoch > start && tickAligned(date, unit, n)) {
            ticks.push(Object.assign({epoch}, tickLabel(date, unit, n, span)));
        }
        if (unit === "h") {
            date.setTime(date.getTime() + 3600000);  // absolute hour: right across daylight saving changes
        } else if (unit === "d") {
            date.setDate(date.getDate() + 1);
        } else if (unit === "m") {
            date.setMonth(date.getMonth() + 1);
        } else {
            date.setFullYear(date.getFullYear() + 1);
        }
    }
    return ticks;
}

function segments(buckets, step) {
    const threshold = Math.max(3 * step, GAP_SECONDS);
    const runs = [];
    let previous = null;
    for (const bucket of buckets) {
        if (previous === null || bucket[0] - previous[0] > threshold) {
            runs.push([]);
        }
        runs[runs.length - 1].push(bucket);
        previous = bucket;
    }
    return runs;
}

// ---- Drawing ----

function plotWidth() {
    return Math.max(100, $("chart").clientWidth - MARGIN.left - MARGIN.right);
}

function render() {
    const data = state.data;
    if (!data) {
        return;
    }
    const svg = $("svg");
    const width = $("chart").clientWidth;
    const height = $("chart").clientHeight;
    const plot = {x: MARGIN.left, y: MARGIN.top, w: width - MARGIN.left - MARGIN.right, h: height - MARGIN.top - MARGIN.bottom};
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    renderSummary(data);
    const buckets = data.buckets;
    if (!buckets.length) {
        svg.innerHTML = '<text x="' + width / 2 + '" y="' + height / 2 + '" text-anchor="middle" fill="' +
            COLOURS.text + '">Pas de mesure sur cette période</text>';
        state.geometry = null;
        return;
    }
    let low = Infinity;
    let high = -Infinity;
    for (const bucket of buckets) {
        low = Math.min(low, bucket[2]);
        high = Math.max(high, bucket[3]);
    }
    const scale = niceTicks(low, high, Math.max(2, Math.floor(plot.h / 45)));
    const yLow = scale.ticks[0];
    const yHigh = scale.ticks[scale.ticks.length - 1];
    const {start, end, step} = data;
    const xOf = (epoch) => plot.x + (epoch - start) * plot.w / (end - start);
    const yOf = (value) => plot.y + (yHigh - value) * plot.h / (yHigh - yLow);
    // A bucket is drawn at its middle, kept inside the period (partial first / last bucket)
    const timeOf = (bucket) => Math.min(Math.max(bucket[0] + step / 2, start), end);
    const point = (bucket, index) => xOf(timeOf(bucket)).toFixed(1) + "," + yOf(bucket[index]).toFixed(1);

    const parts = [];
    for (const value of scale.ticks) {
        const y = yOf(value).toFixed(1);
        parts.push('<line x1="' + plot.x + '" x2="' + (plot.x + plot.w) + '" y1="' + y + '" y2="' + y +
            '" stroke="' + (value === 0 ? COLOURS.zero : COLOURS.grid) + '"/>');
        parts.push('<text x="' + (plot.x - 6) + '" y="' + y + '" text-anchor="end" dominant-baseline="middle"' +
            ' font-size="12" fill="' + COLOURS.text + '">' + formatTick(value, scale.step) + '</text>');
    }
    for (const tick of timeTicks(start, end, Math.max(3, Math.floor(plot.w / 70)))) {
        const x = xOf(tick.epoch).toFixed(1);
        parts.push('<line x1="' + x + '" x2="' + x + '" y1="' + plot.y + '" y2="' + (plot.y + plot.h) +
            '" stroke="' + (tick.major ? COLOURS.gridMajor : COLOURS.grid) + '"/>');
        parts.push('<text x="' + x + '" y="' + (plot.y + plot.h + 19) + '" text-anchor="middle" font-size="12"' +
            ' fill="' + (tick.major ? "#1d2330" : COLOURS.text) + '">' + escapeHtml(tick.label) + '</text>');
    }
    parts.push('<line x1="' + plot.x + '" x2="' + (plot.x + plot.w) + '" y1="' + (plot.y + plot.h) + '" y2="' +
        (plot.y + plot.h) + '" stroke="' + COLOURS.gridMajor + '"/>');
    for (const run of segments(buckets, step)) {
        if (step > 60) {
            // Min-max band of the measures merged in each bucket
            const band = run.map((b) => point(b, 3)).concat(run.slice().reverse().map((b) => point(b, 2)));
            parts.push('<polygon points="' + band.join(" ") + '" fill="' + COLOURS.line + '" fill-opacity="0.18"/>');
        }
        if (run.length === 1) {
            parts.push('<circle cx="' + xOf(timeOf(run[0])).toFixed(1) + '" cy="' + yOf(run[0][1]).toFixed(1) +
                '" r="2" fill="' + COLOURS.line + '"/>');
        } else {
            parts.push('<polyline points="' + run.map((b) => point(b, 1)).join(" ") + '" fill="none" stroke="' +
                COLOURS.line + '" stroke-width="1.6" stroke-linejoin="round"/>');
        }
    }
    parts.push('<rect id="selection" y="' + plot.y + '" height="' + plot.h + '" fill="' + COLOURS.line +
        '" fill-opacity="0.12" visibility="hidden"/>');
    parts.push('<line id="cursor-line" y1="' + plot.y + '" y2="' + (plot.y + plot.h) + '" stroke="#1d2330"' +
        ' stroke-width="1" stroke-dasharray="3,3" visibility="hidden"/>');
    parts.push('<circle id="cursor-dot" r="4" fill="#fff" stroke="' + COLOURS.line + '" stroke-width="2"' +
        ' visibility="hidden"/>');
    svg.innerHTML = parts.join("");
    state.geometry = {plot, xOf, yOf, start, end, step, buckets, times: buckets.map(timeOf)};
}

function renderSummary(data) {
    const sensor = data.sensor;
    $("title").textContent = sensor.label + (sensor.unit ? " (" + sensor.unit + ")" : "");
    document.title = sensor.label + " – Centrale météo St Benoît";
    const last = $("last");
    if (data.last) {
        last.innerHTML = '<span class="value">' + escapeHtml(formatValue(data.last[1], sensor)) + '</span> ' +
            '<span class="when">' + escapeHtml(formatDateTime(data.last[0])) + '</span>';
        last.classList.toggle("stale", data.now - data.last[0] > STALE_SECONDS);
    } else {
        last.textContent = "Aucune mesure";
        last.classList.remove("stale");
    }
    const buckets = data.buckets;
    if (!buckets.length) {
        $("stats").textContent = "";
        return;
    }
    let min = buckets[0];
    let max = buckets[0];
    let sum = 0;
    let count = 0;
    for (const bucket of buckets) {
        if (bucket[2] < min[2]) {
            min = bucket;
        }
        if (bucket[3] > max[3]) {
            max = bucket;
        }
        sum += bucket[1] * bucket[4];
        count += bucket[4];
    }
    const minDate = new Date(min[0] * 1000);
    const maxDate = new Date(max[0] * 1000);
    const when = (date) => data.step >= 86400 ? formatDate(date) : formatDate(date) + " " + formatTime(date);
    $("stats").innerHTML = [
        "Min <b>" + escapeHtml(formatValue(min[2], sensor)) + "</b> " + escapeHtml(when(minDate)),
        "Max <b>" + escapeHtml(formatValue(max[3], sensor)) + "</b> " + escapeHtml(when(maxDate)),
        "Moyenne <b>" + escapeHtml(formatValue(sum / count, sensor)) + "</b>",
        count + " mesures" + (data.sample ? " (une toutes les " + Math.round(data.sample / 60) + " min)" : ""),
    ].map((text) => "<span>" + text + "</span>").join("");
}

// ---- Cursor and zoom ----

function nearestIndex(times, epoch) {
    let low = 0;
    let high = times.length - 1;
    while (high - low > 1) {
        const middle = (low + high) >> 1;
        if (times[middle] < epoch) {
            low = middle;
        } else {
            high = middle;
        }
    }
    return Math.abs(times[low] - epoch) <= Math.abs(times[high] - epoch) ? low : high;
}

function pointerX(event) {
    return event.clientX - $("svg").getBoundingClientRect().left;
}

function hideCursor() {
    for (const id of ["cursor-line", "cursor-dot"]) {
        const element = document.getElementById(id);
        if (element) {
            element.setAttribute("visibility", "hidden");
        }
    }
    $("tooltip").hidden = true;
}

function showCursor(x) {
    const geometry = state.geometry;
    if (!geometry || x < geometry.plot.x - 4 || x > geometry.plot.x + geometry.plot.w + 4) {
        hideCursor();
        return;
    }
    const epoch = geometry.start + (x - geometry.plot.x) * (geometry.end - geometry.start) / geometry.plot.w;
    const index = nearestIndex(geometry.times, epoch);
    const secondsPerPixel = (geometry.end - geometry.start) / geometry.plot.w;
    if (Math.abs(geometry.times[index] - epoch) > Math.max(1.5 * geometry.step, 10 * secondsPerPixel)) {
        hideCursor();  // in a gap of the measures
        return;
    }
    const bucket = geometry.buckets[index];
    const cx = geometry.xOf(geometry.times[index]);
    const cy = geometry.yOf(bucket[1]);
    const line = $("cursor-line");
    line.setAttribute("x1", cx);
    line.setAttribute("x2", cx);
    line.setAttribute("visibility", "visible");
    const dot = $("cursor-dot");
    dot.setAttribute("cx", cx);
    dot.setAttribute("cy", cy);
    dot.setAttribute("visibility", "visible");

    const sensor = state.data.sensor;
    let html = "<div>" + escapeHtml(formatBucket(bucket, geometry.step)) + "</div>" +
        '<div class="value">' + escapeHtml(formatValue(bucket[1], sensor)) + "</div>";
    if (bucket[4] > 1 && bucket[3] - bucket[2] > 0) {
        html += "<div>min " + escapeHtml(formatValue(bucket[2], sensor)) + " · max " +
            escapeHtml(formatValue(bucket[3], sensor)) + "</div>";
    }
    const tooltip = $("tooltip");
    tooltip.innerHTML = html;
    tooltip.hidden = false;
    const chartWidth = $("chart").clientWidth;
    const left = cx + 14 + tooltip.offsetWidth > chartWidth ? cx - 14 - tooltip.offsetWidth : cx + 14;
    tooltip.style.left = Math.max(0, left) + "px";
    tooltip.style.top = Math.max(0, Math.min(cy - tooltip.offsetHeight / 2,
        $("chart").clientHeight - tooltip.offsetHeight)) + "px";
}

function epochAt(x) {
    const geometry = state.geometry;
    const clamped = Math.min(Math.max(x, geometry.plot.x), geometry.plot.x + geometry.plot.w);
    return geometry.start + (clamped - geometry.plot.x) * (geometry.end - geometry.start) / geometry.plot.w;
}

function showSelection(x) {
    const selection = document.getElementById("selection");
    if (!selection || state.drag === null) {
        return;
    }
    const geometry = state.geometry;
    const clamp = (value) => Math.min(Math.max(value, geometry.plot.x), geometry.plot.x + geometry.plot.w);
    const left = Math.min(clamp(x), clamp(state.drag));
    selection.setAttribute("x", left);
    selection.setAttribute("width", Math.abs(clamp(x) - clamp(state.drag)));
    selection.setAttribute("visibility", "visible");
}

function onPointerDown(event) {
    if (!state.geometry) {
        return;
    }
    if (event.pointerType === "mouse" && event.button === 0) {
        state.drag = pointerX(event);
        $("svg").setPointerCapture(event.pointerId);
    }
    showCursor(pointerX(event));
}

function onPointerMove(event) {
    const x = pointerX(event);
    showSelection(x);
    showCursor(x);
}

function onPointerUp(event) {
    if (state.drag === null) {
        return;
    }
    const x = pointerX(event);
    const dragStart = state.drag;
    state.drag = null;
    const selection = document.getElementById("selection");
    if (selection) {
        selection.setAttribute("visibility", "hidden");
    }
    if (!state.geometry) {
        return;
    }
    const from = epochAt(Math.min(dragStart, x));
    const to = epochAt(Math.max(dragStart, x));
    if (Math.abs(x - dragStart) < 8 || to - from < 60) {
        return;  // a click, not a selection
    }
    state.span = Math.max(MIN_SPAN, Math.round(to - from));
    const end = Math.round(Math.max(to, from + state.span));
    state.end = end >= nowEpoch() ? null : end;
    load();
}

// ---- Loading and controls ----

function readUrl() {
    const params = new URLSearchParams(location.search);
    state.sensor = params.get("sensor");
    const span = parseInt(params.get("span"), 10);
    if (span >= MIN_SPAN && span <= MAX_SPAN) {
        state.span = span;
    }
    const end = parseInt(params.get("end"), 10);
    state.end = end > 0 && end < nowEpoch() ? end : null;
}

function writeUrl() {
    const params = new URLSearchParams();
    if (state.sensor) {
        params.set("sensor", state.sensor);
    }
    if (state.span !== DEFAULT_SPAN) {
        params.set("span", state.span);
    }
    if (state.end !== null) {
        params.set("end", state.end);
    }
    history.replaceState(null, "", "?" + params.toString());
}

function setStatus(text) {
    $("status").textContent = text || "";
    $("status").hidden = !text;
    $("chart").classList.toggle("loading", Boolean(text));
}

function fillSensors(sensors, selected) {
    const select = $("sensor");
    const names = sensors.map((s) => s.name).join(",");
    if (select.dataset.names !== names) {
        select.innerHTML = "";
        for (const sensor of sensors) {
            select.add(new Option(sensor.label + (sensor.unit ? " (" + sensor.unit + ")" : ""), sensor.name));
        }
        select.dataset.names = names;
    }
    if (selected) {
        select.value = selected;
    }
}

function updateControls() {
    for (const button of document.querySelectorAll("button[data-span]")) {
        button.classList.toggle("active", Number(button.dataset.span) === state.span);
    }
    const data = state.data;
    const start = data ? data.start : null;
    $("previous").disabled = Boolean(data && data.first !== null && start <= data.first);
    $("next").disabled = state.end === null;
    $("now").disabled = state.end === null;
    const end = state.end === null ? nowEpoch() : state.end;
    $("range").textContent = formatDateTime(end - state.span) + " → " + (state.end === null ? "maintenant" : formatDateTime(end));
}

async function load() {
    if (state.request) {
        state.request.abort();
    }
    const controller = new AbortController();
    state.request = controller;
    state.points = Math.round(plotWidth());
    const params = new URLSearchParams({span: state.span, points: state.points});
    if (state.sensor) {
        params.set("sensor", state.sensor);
    }
    if (state.end !== null) {
        params.set("end", state.end);
    }
    writeUrl();
    updateControls();
    hideCursor();
    setStatus("Chargement…");
    try {
        const response = await fetch("/measures.json?" + params.toString(), {signal: controller.signal});
        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }
        const data = await response.json();
        if (data.sensors) {
            fillSensors(data.sensors, data.sensor ? data.sensor.name : state.sensor);
        }
        if (data.error) {
            setStatus(data.error);
            return;
        }
        state.data = data;
        state.sensor = data.sensor.name;
        state.loadedAt = Date.now();
        writeUrl();
        render();
        setStatus(null);
    } catch (error) {
        if (error.name !== "AbortError") {
            setStatus("Échec du chargement des mesures (" + error.message + ")");
        }
    } finally {
        if (state.request === controller) {
            state.request = null;
        }
        updateControls();
    }
}

function previousPeriod() {
    if ($("previous").disabled) {
        return;
    }
    state.end = (state.end === null ? nowEpoch() : state.end) - state.span;
    load();
}

function nextPeriod() {
    if (state.end === null) {
        return;
    }
    const end = state.end + state.span;
    state.end = end >= nowEpoch() ? null : end;
    load();
}

function latestPeriod() {
    if (state.end !== null) {
        state.end = null;
        load();
    }
}

function init() {
    readUrl();
    const svg = $("svg");
    svg.addEventListener("pointerdown", onPointerDown);
    svg.addEventListener("pointermove", onPointerMove);
    svg.addEventListener("pointerup", onPointerUp);
    svg.addEventListener("pointercancel", () => {
        state.drag = null;
        hideCursor();
    });
    svg.addEventListener("pointerleave", (event) => {
        if (event.pointerType === "mouse" && state.drag === null) {
            hideCursor();
        }
    });
    $("sensor").addEventListener("change", (event) => {
        state.sensor = event.target.value;
        load();
    });
    for (const button of document.querySelectorAll("button[data-span]")) {
        button.addEventListener("click", () => {
            state.span = Number(button.dataset.span);
            load();
        });
    }
    $("previous").addEventListener("click", previousPeriod);
    $("next").addEventListener("click", nextPeriod);
    $("now").addEventListener("click", latestPeriod);
    document.addEventListener("keydown", (event) => {
        if (event.target.tagName === "SELECT" || event.altKey || event.ctrlKey || event.metaKey) {
            return;
        }
        const actions = {ArrowLeft: previousPeriod, ArrowRight: nextPeriod, End: latestPeriod};
        if (actions[event.key]) {
            event.preventDefault();
            actions[event.key]();
        }
    });
    let resizeTimer = null;
    window.addEventListener("resize", () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            // Much wider than when loaded: reload for a finer graph, otherwise just redraw
            if (plotWidth() > 1.5 * state.points && !state.request) {
                load();
            } else {
                render();
            }
        }, 200);
    });
    setInterval(() => {
        if (state.end === null && !document.hidden && !state.request) {
            load();
        }
    }, REFRESH_MS);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && state.end === null && !state.request && Date.now() - state.loadedAt > REFRESH_MS) {
            load();
        }
    });
    load();
}

init();

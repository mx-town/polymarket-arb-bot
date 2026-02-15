"""Post-run log analysis dashboard.

FastAPI server that parses bot log files and renders a 4-tab browser dashboard.
Run: uv run dashboard → http://localhost:8050
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

from .log_parser import parse_log

app = FastAPI(title="Complete-Set Dashboard")

LOG_DIRS = [Path("logs"), Path("logs/dry"), Path("logs/live")]


def _find_logs() -> list[dict]:
    """Find all .log files across log directories, sorted newest first."""
    seen: set[Path] = set()
    logs: list[dict] = []
    for d in LOG_DIRS:
        if not d.exists():
            continue
        for f in d.glob("*.log"):
            resolved = f.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            stat = f.stat()
            logs.append({
                "path": str(f),
                "name": f.name,
                "dir": str(f.parent),
                "size_kb": stat.st_size // 1024,
                "mtime": stat.st_mtime,
            })
    logs.sort(key=lambda x: x["mtime"], reverse=True)
    return logs


_parse_cache: dict[str, tuple[float, dict]] = {}


@app.get("/api/report/{filepath:path}")
async def api_report(filepath: str):
    """Return parsed log data as JSON; cache by file mtime."""
    p = Path(filepath)
    if not p.exists():
        return {"error": "not found"}
    mtime = p.stat().st_mtime
    cached = _parse_cache.get(filepath)
    if cached and cached[0] == mtime:
        return cached[1]
    data = parse_log(p)
    _parse_cache[filepath] = (mtime, data)
    return data


@app.get("/", response_class=HTMLResponse)
async def index():
    logs = _find_logs()
    rows = ""
    for lg in logs:
        mode = "dry" if "/dry/" in lg["path"] else "live" if "/live/" in lg["path"] else "?"
        badge_color = "#4a9eff" if mode == "dry" else "#ff6b6b" if mode == "live" else "#888"
        rows += f"""
        <tr onclick="window.location='/report/{lg['path']}'" style="cursor:pointer">
            <td><span style="background:{badge_color};padding:2px 8px;border-radius:4px;font-size:0.8em">{mode}</span></td>
            <td style="font-family:monospace">{lg['name']}</td>
            <td style="color:#888">{lg['dir']}</td>
            <td style="text-align:right">{lg['size_kb']} KB</td>
        </tr>"""
    return f"""<!DOCTYPE html>
<html><head>
<title>Dashboard — Log Files</title>
<style>
    * {{ margin:0; padding:0; box-sizing:border-box }}
    body {{ background:#1a1a2e; color:#eee; font-family:'SF Mono','Fira Code',monospace; padding:40px }}
    h1 {{ color:#4a9eff; margin-bottom:24px; font-size:1.4em }}
    table {{ width:100%; border-collapse:collapse }}
    th {{ text-align:left; padding:10px 12px; color:#888; border-bottom:1px solid #333; font-size:0.85em }}
    td {{ padding:10px 12px; border-bottom:1px solid #222 }}
    tr:hover {{ background:#16213e }}
    .empty {{ color:#666; padding:40px; text-align:center }}
</style>
</head><body>
<h1>Complete-Set Arb — Log Dashboard</h1>
{"<table><tr><th></th><th>File</th><th>Directory</th><th>Size</th></tr>" + rows + "</table>" if logs else '<div class="empty">No log files found in logs/, logs/dry/, or logs/live/</div>'}
</body></html>"""


# language=html
REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html><head>
<title>Dashboard — __FILENAME__</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3"></script>
<style>
    * { margin:0; padding:0; box-sizing:border-box }
    body { background:#1a1a2e; color:#eee; font-family:'SF Mono','Fira Code',monospace; font-size:13px }
    .header { background:#16213e; padding:12px 24px; display:flex; align-items:center; gap:16px; border-bottom:1px solid #333 }
    .header a { color:#4a9eff; text-decoration:none; font-size:0.9em }
    .header h1 { font-size:1.1em; color:#fff; flex:1 }
    .header .meta { color:#888; font-size:0.85em }
    .tabs { display:flex; background:#0f3460; border-bottom:2px solid #4a9eff }
    .tab { padding:10px 20px; cursor:pointer; color:#888; border-bottom:2px solid transparent; margin-bottom:-2px; transition:all 0.2s }
    .tab:hover { color:#ccc }
    .tab.active { color:#4a9eff; border-bottom-color:#4a9eff }
    .view { display:none; padding:24px }
    .view.active { display:block }
    .card { background:#16213e; border-radius:8px; padding:16px; margin-bottom:16px }
    .card h3 { color:#4a9eff; margin-bottom:12px; font-size:0.95em }
    .metric-row { display:flex; gap:16px; flex-wrap:wrap; margin-bottom:16px }
    .metric { background:#16213e; border-radius:8px; padding:16px 20px; min-width:140px; flex:1 }
    .metric .label { color:#888; font-size:0.8em; margin-bottom:4px }
    .metric .value { font-size:1.6em; font-weight:bold }
    .metric .value.green { color:#4ade80 }
    .metric .value.red { color:#f87171 }
    .metric .value.yellow { color:#fbbf24 }
    table.data { width:100%; border-collapse:collapse }
    table.data th { text-align:left; padding:8px 10px; color:#888; border-bottom:1px solid #333; font-size:0.8em; white-space:nowrap }
    table.data td { padding:8px 10px; border-bottom:1px solid #222; white-space:nowrap }
    tr.green { background:rgba(74,222,128,0.08) }
    tr.red { background:rgba(248,113,113,0.08) }
    tr.yellow { background:rgba(251,191,36,0.05) }
    .flag-card { border:1px solid #f87171; border-radius:6px; padding:12px; margin-bottom:8px; background:rgba(248,113,113,0.05) }
    .flag-card .flag-name { color:#f87171; font-weight:bold; font-size:0.85em }
    .flag-card .flag-detail { color:#ccc; margin-top:4px; font-size:0.85em }
    .alert { background:rgba(248,113,113,0.15); border:1px solid #f87171; border-radius:6px; padding:12px; margin-bottom:16px; color:#f87171 }
    .config-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:8px }
    .config-item { display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid #222 }
    .config-item .k { color:#888 }
    .config-item .v { color:#eee }
    canvas { max-height:350px }
    .chart-wrap { position:relative; height:350px; margin-bottom:16px }
    /* BTC chart overrides */
    .btc-chart-wrap { position:relative; height:550px; margin-bottom:0 }
    .btc-chart-wrap canvas { max-height:550px }
    .toolbar { display:flex; align-items:center; gap:8px; padding:10px 0; flex-wrap:wrap }
    .toolbar .sep { width:1px; height:20px; background:#333; margin:0 4px }
    .btn { background:#0f3460; border:1px solid #333; color:#ccc; padding:5px 12px; border-radius:4px; cursor:pointer; font-family:inherit; font-size:0.8em; transition:all 0.15s }
    .btn:hover { background:#1a4a8a; border-color:#4a9eff; color:#fff }
    .btn.active { background:#4a9eff; color:#fff; border-color:#4a9eff }
    .btn.danger { border-color:#f87171 }
    .btn.danger:hover { background:#7f1d1d }
    .crosshair-info { color:#888; font-size:0.8em; margin-left:auto; min-width:300px; text-align:right }
    .crosshair-info b { color:#fbbf24 }
    .event-row { cursor:pointer; transition:background 0.15s }
    .event-row:hover { background:#1a4a8a !important }
</style>
</head><body>

<div class="header">
    <a href="/">&larr; Back</a>
    <h1>__FILENAME__</h1>
    <span class="meta" id="header-meta">__START__ &mdash; __END__ | __MODE__</span>
    <span id="refresh-timer" style="color:#888;font-size:0.85em;min-width:80px">&mdash;</span>
    <button onclick="fetchData()" style="background:#0f3460;border:1px solid #333;color:#ccc;padding:4px 12px;border-radius:4px;cursor:pointer;font-family:inherit;font-size:0.8em">Refresh</button>
    <button id="auto-toggle" onclick="toggleAuto()" style="background:#0f3460;border:1px solid #4a9eff;color:#4a9eff;padding:4px 12px;border-radius:4px;cursor:pointer;font-family:inherit;font-size:0.8em">Auto: ON</button>
</div>

<div class="tabs">
    <div class="tab active" onclick="showTab(0)">Pipeline</div>
    <div class="tab" onclick="showTab(1)">Markets</div>
    <div class="tab" onclick="showTab(2)">P&amp;L</div>
    <div class="tab" onclick="showTab(3)">BTC Overlay</div>
</div>

<!-- TAB 0: Pipeline Funnel -->
<div class="view active" id="v0">
    <div class="metric-row">
        <div class="metric"><div class="label">Entries</div><div class="value" id="f-entries">-</div></div>
        <div class="metric"><div class="label">Fills</div><div class="value" id="f-fills">-</div></div>
        <div class="metric"><div class="label">Hedges Complete</div><div class="value" id="f-hedges">-</div></div>
        <div class="metric"><div class="label">Merges</div><div class="value" id="f-merges">-</div></div>
        <div class="metric"><div class="label">Unhedged Losses</div><div class="value red" id="f-unhedged">-</div></div>
    </div>
    <div id="hedge-alert"></div>
    <div class="card">
        <h3>Pipeline Funnel</h3>
        <div class="chart-wrap"><canvas id="funnelChart"></canvas></div>
    </div>
    <div class="card">
        <h3>Conversion Rates</h3>
        <div id="conv-rates" style="display:flex;gap:32px;flex-wrap:wrap"></div>
    </div>
</div>

<!-- TAB 1: Per-Market Lifecycle -->
<div class="view" id="v1">
    <div class="card">
        <h3>Per-Market Lifecycle</h3>
        <div style="overflow-x:auto">
            <table class="data" id="market-table">
                <thead><tr>
                    <th>Slug</th><th>Entry</th><th>Price</th><th>Fill</th><th>Hedge</th>
                    <th>Combined</th><th>Edge</th><th>P&amp;L</th><th>Reprices</th><th>Status</th>
                </tr></thead>
                <tbody></tbody>
            </table>
        </div>
    </div>
</div>

<!-- TAB 2: P&L + Session -->
<div class="view" id="v2">
    <div class="metric-row">
        <div class="metric"><div class="label">Total P&amp;L</div><div class="value" id="pnl-total">-</div></div>
        <div class="metric"><div class="label">ROI</div><div class="value" id="pnl-roi">-</div></div>
        <div class="metric"><div class="label">Merges</div><div class="value" id="pnl-merges">-</div></div>
        <div class="metric"><div class="label">Losses</div><div class="value red" id="pnl-losses">-</div></div>
    </div>
    <div class="card">
        <h3>P&amp;L Over Time</h3>
        <div class="chart-wrap"><canvas id="pnlChart"></canvas></div>
    </div>
    <div class="card" id="flags-section">
        <h3>Red Flags</h3>
        <div id="flags-list"></div>
    </div>
    <div class="card">
        <h3>Config</h3>
        <div class="config-grid" id="config-grid"></div>
    </div>
</div>

<!-- TAB 3: BTC Overlay -->
<div class="view" id="v3">
    <div class="card" style="padding-bottom:8px">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
            <h3 style="margin:0">BTC Price + Trading Events</h3>
            <span id="btc-range" style="color:#888;font-size:0.8em"></span>
        </div>
        <div class="toolbar" id="btc-toolbar">
            <button class="btn active" onclick="btcZoomAll()">All</button>
            <div class="sep"></div>
            <span style="color:#555;font-size:0.75em">MARKETS:</span>
            <div id="market-btns"></div>
            <div class="sep"></div>
            <button class="btn" onclick="btcZoomIn()">Zoom +</button>
            <button class="btn" onclick="btcZoomOut()">Zoom &minus;</button>
            <button class="btn danger" onclick="btcZoomAll()">Reset</button>
            <span class="crosshair-info" id="crosshair-info">Scroll to zoom &middot; Drag to pan</span>
        </div>
        <div class="btc-chart-wrap"><canvas id="btcChart"></canvas></div>
    </div>
    <div class="card">
        <h3>Events</h3>
        <div style="overflow-x:auto">
            <table class="data" id="events-table">
                <thead><tr><th>Time</th><th>Type</th><th>Slug</th><th>Side</th><th>Poly Price</th><th>BTC Price</th></tr></thead>
                <tbody></tbody>
            </table>
        </div>
    </div>
</div>

<script>
const FILEPATH = __FILEPATH_JSON__;
let D = null;
let lastRefreshMs = 0;
let autoRefreshOn = true;
let pollId = null;

// Chart instances (reused across renders)
let funnelChartInstance = null;
let pnlChartInstance = null;
let btcChartInstance = null;
let _prevBtcLen = 0;
let _prevEvtLen = 0;

// Tab switching
function showTab(i) {
    document.querySelectorAll('.tab').forEach((t,j) => t.classList.toggle('active', j===i));
    document.querySelectorAll('.view').forEach((v,j) => v.classList.toggle('active', j===i));
}

function pct(a, b) { return b > 0 ? (a/b*100).toFixed(0) + '%' : 'n/a'; }
function timeToSec(t) { const p = t.split(':'); return +p[0]*3600 + +p[1]*60 + +p[2]; }

// --- Render functions ---

function renderPipeline() {
    const f = D.funnel;
    document.getElementById('f-entries').textContent = f.entries;
    document.getElementById('f-fills').textContent = f.fills;
    document.getElementById('f-hedges').textContent = f.hedges_complete;
    document.getElementById('f-merges').textContent = f.merges;
    document.getElementById('f-unhedged').textContent = f.unhedged_count;

    if (f.fills > 0 && f.hedges_complete / f.fills < 0.5) {
        document.getElementById('hedge-alert').innerHTML =
            '<div class="alert">Hedge rate below 50% \u2014 most first legs are resolving as losses</div>';
    } else {
        document.getElementById('hedge-alert').innerHTML = '';
    }

    const chartData = [f.entries, f.fills, f.hedge_attempts, f.hedges_complete, f.merges];
    if (funnelChartInstance) {
        funnelChartInstance.data.datasets[0].data = chartData;
        funnelChartInstance.update('none');
    } else {
        funnelChartInstance = new Chart(document.getElementById('funnelChart'), {
            type: 'bar',
            data: {
                labels: ['Entries', 'Fills', 'Hedge Attempts', 'Hedges Complete', 'Merges'],
                datasets: [{
                    data: chartData,
                    backgroundColor: ['#4a9eff', '#4ade80', '#fbbf24', '#22d3ee', '#a78bfa'],
                    borderRadius: 4,
                }]
            },
            options: {
                indexAxis: 'y',
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: '#222' }, ticks: { color: '#888' } },
                    y: { grid: { display: false }, ticks: { color: '#ccc' } }
                }
            }
        });
    }

    const rates = document.getElementById('conv-rates');
    rates.innerHTML =
        '<div><span style="color:#888">Fill rate:</span> <b>' + pct(f.fills, f.entries) + '</b></div>' +
        '<div><span style="color:#888">Hedge rate:</span> <b>' + pct(f.hedges_complete, f.fills) + '</b></div>' +
        '<div><span style="color:#888">Merge rate:</span> <b>' + pct(f.merges, f.hedges_complete) + '</b></div>';
}

function renderMarkets() {
    const tbody = document.querySelector('#market-table tbody');
    tbody.innerHTML = '';
    D.markets.forEach(m => {
        const slug = m.slug.length > 30 ? '...' + m.slug.slice(-27) : m.slug;
        const chaseIcon = m.price_chasing ? ' <span title="Price chasing detected" style="color:#f97316">&#9888;</span>' : '';
        const pnl = m.pnl !== null ? '$' + m.pnl.toFixed(2) : '-';
        const pnlColor = m.pnl !== null ? (m.pnl >= 0 ? 'color:#4ade80' : 'color:#f87171') : '';
        const edge = m.hedge_edge !== null ? m.hedge_edge.toFixed(3) : '-';
        const combined = m.combined_cost !== null ? m.combined_cost.toFixed(2) : '-';
        const tr = document.createElement('tr');
        tr.className = m.status;
        tr.innerHTML =
            '<td title="' + m.slug + '">' + slug + '</td>' +
            '<td>' + (m.entry_side || '-') + ' ' + (m.entry_type ? '(' + m.entry_type.replace('_ENTRY','') + ')' : '') + '</td>' +
            '<td>' + (m.entry_price !== null ? m.entry_price.toFixed(2) : '-') + '</td>' +
            '<td>' + (m.fill_time || '-') + '</td>' +
            '<td>' + (m.hedge_price !== null ? m.hedge_price.toFixed(2) : '-') + '</td>' +
            '<td>' + combined + '</td>' +
            '<td>' + edge + '</td>' +
            '<td style="' + pnlColor + '">' + pnl + '</td>' +
            '<td>' + m.reprice_count + chaseIcon + '</td>' +
            '<td>' + m.outcome + '</td>';
        tbody.appendChild(tr);
    });
}

function renderPnL() {
    const totalPnl = D.total_realized;
    const pnlEl = document.getElementById('pnl-total');
    pnlEl.textContent = '$' + totalPnl.toFixed(2);
    pnlEl.className = 'value ' + (totalPnl >= 0 ? 'green' : 'red');

    const roiEl = document.getElementById('pnl-roi');
    roiEl.textContent = D.final_roi.toFixed(2) + '%';
    roiEl.className = 'value ' + (D.final_roi >= 0 ? 'green' : 'red');

    const f = D.funnel;
    document.getElementById('pnl-merges').textContent = f.merges;
    document.getElementById('pnl-losses').textContent = f.unhedged_count;

    if (D.pnl_snapshots.length > 0) {
        const labels = D.pnl_snapshots.map(s => s.time);
        const realized = D.pnl_snapshots.map(s => s.realized);
        const unrealized = D.pnl_snapshots.map(s => s.unrealized);
        const total = D.pnl_snapshots.map(s => s.total);

        if (pnlChartInstance) {
            pnlChartInstance.data.labels = labels;
            pnlChartInstance.data.datasets[0].data = realized;
            pnlChartInstance.data.datasets[1].data = unrealized;
            pnlChartInstance.data.datasets[2].data = total;
            pnlChartInstance.update('none');
        } else {
            pnlChartInstance = new Chart(document.getElementById('pnlChart'), {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Realized',
                            data: realized,
                            borderColor: '#4ade80',
                            borderWidth: 1.5,
                            pointRadius: 0,
                            fill: false,
                        },
                        {
                            label: 'Unrealized',
                            data: unrealized,
                            borderColor: '#fbbf24',
                            borderWidth: 1.5,
                            pointRadius: 0,
                            fill: false,
                        },
                        {
                            label: 'Total',
                            data: total,
                            borderColor: '#4a9eff',
                            borderWidth: 2,
                            pointRadius: 0,
                            fill: false,
                        }
                    ]
                },
                options: {
                    plugins: { legend: { labels: { color: '#ccc' } } },
                    scales: {
                        x: { grid: { color: '#222' }, ticks: { color: '#888', maxTicksLimit: 15, maxRotation: 0 } },
                        y: { grid: { color: '#222' }, ticks: { color: '#888' } }
                    }
                }
            });
        }
    }

    const flagsList = document.getElementById('flags-list');
    if (D.red_flags.length === 0) {
        flagsList.innerHTML = '<div style="color:#4ade80">No red flags detected</div>';
    } else {
        flagsList.innerHTML = '';
        D.red_flags.forEach(fl => {
            flagsList.innerHTML += '<div class="flag-card"><div class="flag-name">' + fl.flag + '</div><div class="flag-detail">' + fl.detail + '</div></div>';
        });
    }

    const configGrid = document.getElementById('config-grid');
    configGrid.innerHTML = '';
    Object.entries(D.config).forEach(([k, v]) => {
        const display = typeof v === 'boolean' ? (v ? 'ON' : 'OFF') : v;
        configGrid.innerHTML += '<div class="config-item"><span class="k">' + k + '</span><span class="v">' + display + '</span></div>';
    });
}

function renderBTC() {
    if (!D.btc_ticks || D.btc_ticks.length === 0) return;

    const newBtcLen = D.btc_ticks.length;
    const newEvtLen = D.btc_events.length;
    const dataChanged = newBtcLen !== _prevBtcLen || newEvtLen !== _prevEvtLen;
    _prevBtcLen = newBtcLen;
    _prevEvtLen = newEvtLen;

    // If chart exists and data hasn't grown, skip full rebuild (preserves zoom)
    if (btcChartInstance && !dataChanged) return;

    const eventColors = { entry: '#4ade80', fill: '#4a9eff', hedge: '#f97316', merge: '#a78bfa' };
    const eventShapes = { entry: 'triangle', fill: 'circle', hedge: 'rectRot', merge: 'star' };

    const tickTimes = D.btc_ticks.map(t => timeToSec(t.time));
    const btcPrices = D.btc_ticks.map(t => t.price);
    const btcLabels = D.btc_ticks.map(t => t.time);
    const btcMin = Math.min(...btcPrices);
    const btcMax = Math.max(...btcPrices);
    document.getElementById('btc-range').textContent =
        '$' + btcMin.toFixed(0) + ' - $' + btcMax.toFixed(0) + ' (range: $' + (btcMax-btcMin).toFixed(0) + ')';

    function nearestTickIdx(timeStr) {
        const s = timeToSec(timeStr);
        let lo = 0, hi = tickTimes.length - 1;
        while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (tickTimes[mid] < s) lo = mid + 1; else hi = mid;
        }
        if (lo > 0 && Math.abs(tickTimes[lo-1] - s) < Math.abs(tickTimes[lo] - s)) lo--;
        return lo;
    }

    // Build annotation lines for each event
    const annotations = {};
    D.btc_events.forEach(function(e, i) {
        const idx = nearestTickIdx(e.time);
        const label = e.type.toUpperCase() + (e.side ? ' ' + e.side : '');
        annotations['evt' + i] = {
            type: 'line',
            xMin: btcLabels[idx],
            xMax: btcLabels[idx],
            borderColor: eventColors[e.type] + '88',
            borderWidth: 1,
            borderDash: [4, 3],
            label: {
                display: true,
                content: label,
                position: i % 2 === 0 ? 'start' : 'end',
                backgroundColor: eventColors[e.type] + 'cc',
                color: '#fff',
                font: { size: 10, family: 'monospace' },
                padding: { top: 2, bottom: 2, left: 4, right: 4 },
                borderRadius: 3,
            }
        };
    });

    // Market window shading
    var windowColors = ['rgba(74,158,255,0.04)', 'rgba(168,85,247,0.04)', 'rgba(251,191,36,0.04)', 'rgba(74,222,128,0.04)'];
    D.markets.forEach(function(m, i) {
        if (!m.enter_time || !m.exit_time) return;
        var enterIdx = nearestTickIdx(m.enter_time);
        var exitIdx = nearestTickIdx(m.exit_time);
        if (enterIdx >= exitIdx) return;
        annotations['win' + i] = {
            type: 'box',
            xMin: btcLabels[enterIdx],
            xMax: btcLabels[exitIdx],
            backgroundColor: windowColors[i % windowColors.length],
            borderWidth: 0,
            label: {
                display: true,
                content: '...' + m.slug.slice(-15),
                position: { x: 'start', y: 'start' },
                color: '#666',
                font: { size: 9, family: 'monospace' },
                padding: 2,
            }
        };
    });

    // Build scatter datasets per event type
    var eventDatasets = {};
    D.btc_events.forEach(function(e) {
        if (!eventDatasets[e.type]) {
            eventDatasets[e.type] = {
                label: e.type.charAt(0).toUpperCase() + e.type.slice(1),
                data: [],
                type: 'scatter',
                pointStyle: eventShapes[e.type] || 'circle',
                pointRadius: 10,
                pointHoverRadius: 14,
                backgroundColor: eventColors[e.type] || '#fff',
                borderColor: '#fff',
                borderWidth: 2,
                order: -1,
            };
        }
        var idx = nearestTickIdx(e.time);
        eventDatasets[e.type].data.push({
            x: btcLabels[idx],
            y: e.btc_price,
            slug: e.slug,
            side: e.side,
            poly_price: e.poly_price,
        });
    });

    // Crosshair plugin
    var crosshairPlugin = {
        id: 'crosshair',
        afterEvent: function(chart, args) {
            var evt = args.event;
            if (evt.type === 'mousemove' && args.inChartArea) {
                chart._crosshairX = evt.x;
                chart._crosshairY = evt.y;
                chart._showCrosshair = true;
                var xScale = chart.scales.x;
                var idx = Math.round(xScale.getValueForPixel(evt.x));
                idx = Math.max(0, Math.min(btcLabels.length - 1, idx));
                var time = btcLabels[idx] || '';
                var btcAtIdx = btcPrices[idx];
                var info = document.getElementById('crosshair-info');
                if (info && time && btcAtIdx !== undefined) {
                    var delta = btcAtIdx - btcPrices[0];
                    var sign = delta >= 0 ? '+' : '';
                    var color = delta >= 0 ? '#4ade80' : '#f87171';
                    info.textContent = time + '  $' + btcAtIdx.toFixed(2) + '  ' + sign + delta.toFixed(2);
                    info.style.color = color;
                }
            } else if (evt.type === 'mouseout') {
                chart._showCrosshair = false;
                var info2 = document.getElementById('crosshair-info');
                if (info2) { info2.textContent = 'Scroll to zoom | Drag to pan'; info2.style.color = '#888'; }
            }
            chart.draw();
        },
        afterDraw: function(chart) {
            if (!chart._showCrosshair) return;
            var ctx = chart.ctx;
            var area = chart.chartArea;
            ctx.save();
            ctx.strokeStyle = '#ffffff44';
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(chart._crosshairX, area.top);
            ctx.lineTo(chart._crosshairX, area.bottom);
            ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(area.left, chart._crosshairY);
            ctx.lineTo(area.right, chart._crosshairY);
            ctx.stroke();
            ctx.restore();
        }
    };

    // Destroy old chart and rebuild (BTC chart is complex with annotations/zoom)
    if (btcChartInstance) {
        btcChartInstance.destroy();
        btcChartInstance = null;
    }

    btcChartInstance = new Chart(document.getElementById('btcChart'), {
        type: 'line',
        plugins: [crosshairPlugin],
        data: {
            labels: btcLabels,
            datasets: [
                {
                    label: 'BTC Price',
                    data: btcPrices,
                    borderColor: '#fbbf24',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: { target: 'origin', above: 'rgba(251,191,36,0.05)' },
                    tension: 0,
                },
                ...Object.values(eventDatasets),
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    labels: { color: '#ccc', usePointStyle: true, pointStyle: 'circle', padding: 16 },
                    position: 'top',
                },
                tooltip: {
                    backgroundColor: '#1a1a2eee',
                    borderColor: '#333',
                    borderWidth: 1,
                    titleFont: { family: 'monospace' },
                    bodyFont: { family: 'monospace' },
                    padding: 10,
                    callbacks: {
                        label: function(ctx) {
                            var raw = ctx.raw;
                            if (raw && raw.slug) {
                                var slug = raw.slug.length > 25 ? '...' + raw.slug.slice(-22) : raw.slug;
                                return ctx.dataset.label + ': ' + slug + ' ' + (raw.side || '') + ' @' + (raw.poly_price || '-') + ' | BTC $' + raw.y.toFixed(2);
                            }
                            return 'BTC: $' + ctx.parsed.y.toFixed(2);
                        }
                    }
                },
                annotation: { annotations: annotations },
                zoom: {
                    pan: { enabled: true, mode: 'x', modifierKey: null },
                    zoom: {
                        wheel: { enabled: true, modifierKey: null },
                        pinch: { enabled: true },
                        drag: { enabled: false },
                        mode: 'x',
                    },
                    limits: { x: { minRange: 10 } },
                },
            },
            scales: {
                x: {
                    grid: { color: '#1a1a2e', tickColor: '#333' },
                    ticks: { color: '#888', maxTicksLimit: 20, maxRotation: 0, font: { size: 10, family: 'monospace' } },
                    border: { color: '#333' },
                },
                y: {
                    grid: { color: '#222' },
                    ticks: {
                        color: '#888',
                        font: { size: 10, family: 'monospace' },
                        callback: function(v) { return '$' + v.toLocaleString(); },
                    },
                    border: { color: '#333' },
                    position: 'right',
                }
            }
        }
    });

    // Build per-market zoom buttons
    var mktBtns = document.getElementById('market-btns');
    mktBtns.innerHTML = '';
    D.markets.forEach(function(m) {
        if (!m.enter_time) return;
        var btn = document.createElement('button');
        btn.className = 'btn';
        btn.textContent = '...' + m.slug.slice(-12);
        btn.title = m.slug;
        if (m.status === 'green') btn.style.borderLeft = '3px solid #4ade80';
        else if (m.status === 'red') btn.style.borderLeft = '3px solid #f87171';
        btn.onclick = function() { btcZoomToMarket(m); };
        mktBtns.appendChild(btn);
    });

    // Events table
    var evTbody = document.querySelector('#events-table tbody');
    evTbody.innerHTML = '';
    var typeColors = { entry: '#4ade80', fill: '#4a9eff', hedge: '#f97316', merge: '#a78bfa' };
    D.btc_events.forEach(function(e) {
        var slug = e.slug.length > 30 ? '...' + e.slug.slice(-27) : e.slug;
        var tr = document.createElement('tr');
        tr.className = 'event-row';
        tr.title = 'Click to zoom to this event';

        var td1 = document.createElement('td'); td1.textContent = e.time;
        var td2 = document.createElement('td'); td2.textContent = e.type; td2.style.color = typeColors[e.type] || '#eee';
        var td3 = document.createElement('td'); td3.textContent = slug; td3.title = e.slug;
        var td4 = document.createElement('td'); td4.textContent = e.side || '-';
        var td5 = document.createElement('td'); td5.textContent = e.poly_price !== null ? e.poly_price.toFixed(2) : '-';
        var td6 = document.createElement('td'); td6.textContent = '$' + e.btc_price.toFixed(2);

        tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3);
        tr.appendChild(td4); tr.appendChild(td5); tr.appendChild(td6);

        tr.onclick = (function(ev) {
            return function() {
                if (!btcChartInstance) return;
                var labels = btcChartInstance.data.labels;
                var sec = timeToSec(ev.time);
                var center = 0;
                for (var k = 0; k < labels.length; k++) {
                    if (timeToSec(labels[k]) >= sec) { center = k; break; }
                }
                var half = Math.min(60, Math.floor(labels.length / 4));
                btcChartInstance.zoomScale('x', { min: Math.max(0, center - half), max: Math.min(labels.length - 1, center + half) }, 'default');
            };
        })(e);

        evTbody.appendChild(tr);
    });
}

function renderAll() {
    if (!D) return;
    // Update header meta
    document.getElementById('header-meta').textContent =
        D.start_time + ' \u2014 ' + D.end_time + ' | ' + D.mode.toUpperCase();
    renderPipeline();
    renderMarkets();
    renderPnL();
    renderBTC();
}

// --- BTC zoom helpers (reference btcChartInstance) ---

function btcZoomAll() {
    if (!btcChartInstance) return;
    btcChartInstance.resetZoom();
    document.querySelectorAll('#btc-toolbar .btn').forEach(function(b) { b.classList.remove('active'); });
    document.querySelector('#btc-toolbar .btn').classList.add('active');
}

function btcZoomIn() {
    if (!btcChartInstance) return;
    btcChartInstance.zoom(1.5);
}

function btcZoomOut() {
    if (!btcChartInstance) return;
    btcChartInstance.zoom(0.67);
}

function btcZoomToMarket(m) {
    if (!btcChartInstance || !m.enter_time) return;
    var labels = btcChartInstance.data.labels;
    var enterSec = timeToSec(m.enter_time);
    var exitSec = m.exit_time ? timeToSec(m.exit_time) : (m.clear_time ? timeToSec(m.clear_time) : enterSec + 900);
    var padSec = 60;
    var minIdx = 0, maxIdx = labels.length - 1;
    for (var i = 0; i < labels.length; i++) {
        if (timeToSec(labels[i]) >= enterSec - padSec) { minIdx = i; break; }
    }
    for (var j = labels.length - 1; j >= 0; j--) {
        if (timeToSec(labels[j]) <= exitSec + padSec) { maxIdx = j; break; }
    }
    btcChartInstance.zoomScale('x', { min: minIdx, max: maxIdx }, 'default');
    document.querySelectorAll('#btc-toolbar .btn').forEach(function(b) { b.classList.remove('active'); });
}

// --- Polling ---

async function fetchData() {
    try {
        const resp = await fetch('/api/report/' + FILEPATH);
        if (!resp.ok) return;
        D = await resp.json();
        if (D.error) { D = null; return; }
        lastRefreshMs = Date.now();
        renderAll();
    } catch (e) {
        // network error, skip this tick
    }
}

function timerTick() {
    const el = document.getElementById('refresh-timer');
    if (!lastRefreshMs) { el.textContent = '\u2014'; return; }
    const ago = ((Date.now() - lastRefreshMs) / 1000).toFixed(1);
    el.textContent = ago + 's ago';
}

function toggleAuto() {
    autoRefreshOn = !autoRefreshOn;
    const btn = document.getElementById('auto-toggle');
    if (autoRefreshOn) {
        btn.textContent = 'Auto: ON';
        btn.style.color = '#4a9eff';
        btn.style.borderColor = '#4a9eff';
        pollId = setInterval(fetchData, 1000);
    } else {
        btn.textContent = 'Auto: OFF';
        btn.style.color = '#888';
        btn.style.borderColor = '#333';
        if (pollId) { clearInterval(pollId); pollId = null; }
    }
}

// Boot
fetchData();
pollId = setInterval(fetchData, 1000);
setInterval(timerTick, 200);
</script>
</body></html>"""


@app.get("/report/{filepath:path}", response_class=HTMLResponse)
async def report(filepath: str):
    p = Path(filepath)
    if not p.exists():
        return HTMLResponse(f"<h1>File not found: {filepath}</h1>", status_code=404)

    data = parse_log(p)
    filepath_json = json.dumps(filepath)

    html = REPORT_TEMPLATE
    html = html.replace("__FILENAME__", data["filename"])
    html = html.replace("__START__", data["start_time"])
    html = html.replace("__END__", data["end_time"])
    html = html.replace("__MODE__", data["mode"].upper())
    html = html.replace("__FILEPATH_JSON__", filepath_json)

    return HTMLResponse(html)


def main():
    print("Starting dashboard at http://localhost:8050")
    uvicorn.run(app, host="0.0.0.0", port=8050, log_level="warning")


if __name__ == "__main__":
    main()

/**
 * Golf Betting Model — Dashboard JS
 * Vanilla JS, Bootstrap 5, no external dependencies.
 */

'use strict';

// ── Global state ─────────────────────────────────────────────────────────────
let ALL_PLAYERS = [];
let CURRENT_FILTER = 'all';
let HISTORY_LOADED = false;
let LEADERBOARD_LOADED = false;
const TOURNAMENT_DETAIL_CACHE = {}; // event_id → fetched rows

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  fetchData();
});

// ── Data fetching ─────────────────────────────────────────────────────────────
async function fetchData() {
  try {
    const res = await fetch('/api/data');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAll(data);
  } catch (err) {
    showAlert(`Failed to load data: ${err.message}`, 'danger');
    document.getElementById('playerTableBody').innerHTML =
      `<tr><td colspan="16" class="text-center text-muted py-4">
        No data — click <strong>Refresh Data</strong> to fetch.
      </td></tr>`;
  }
}

// ── Render orchestrator ───────────────────────────────────────────────────────
function renderAll(data) {
  renderTournament(data.tournament);
  renderWeather(data.weather || []);
  renderMeta(data);
  ALL_PLAYERS = data.players || [];
  applyFilters();
  renderCredits(data.odds_credits_remaining);
  renderWarnings(data.data_warnings || []);
}

// ── Tournament header ─────────────────────────────────────────────────────────
function renderTournament(t) {
  if (!t) {
    document.getElementById('tournamentName').textContent = 'No Tournament Data';
    return;
  }
  document.getElementById('tournamentName').textContent = t.event_name || 'Golf Tournament';
  const meta = [
    t.course_name,
    t.location,
    t.start_date && t.end_date ? `${t.start_date} – ${t.end_date}` : (t.start_date || ''),
    t.tour ? t.tour.toUpperCase() : '',
  ].filter(Boolean).join(' · ');
  document.getElementById('tournamentMeta').textContent = meta;
  document.title = (t.event_name || 'Golf Model') + ' — Golf Betting Model';
}

// ── Meta / timestamps ─────────────────────────────────────────────────────────
function renderMeta(data) {
  const ts = data.last_refreshed;
  const isStale = data.is_stale;

  const formatted = ts ? formatTimestamp(ts) : 'Never';
  document.getElementById('lastUpdatedFull').textContent = `Updated: ${formatted}`;
  document.getElementById('lastUpdatedNav').textContent = `Updated: ${formatted}`;

  const staleBadge = document.getElementById('staleBadge');
  if (isStale) {
    staleBadge.classList.remove('d-none');
  } else {
    staleBadge.classList.add('d-none');
  }
}

function renderCredits(credits) {
  const el = document.getElementById('oddsCredits');
  if (credits !== null && credits !== undefined) {
    el.textContent = `Odds API credits remaining: ${credits.toLocaleString()}`;
  } else {
    el.textContent = '';
  }
}

function renderWarnings(warnings) {
  if (!warnings || warnings.length === 0) return;
  const alertArea = document.getElementById('alertArea');
  const html = warnings.map(w => `<li>${escHtml(w)}</li>`).join('');
  alertArea.innerHTML = `
    <div class="alert alert-warning alert-dismissible fade show py-2" role="alert">
      <strong>Data warnings:</strong>
      <ul class="mb-0 mt-1">${html}</ul>
      <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>`;
}

// ── Weather cards ─────────────────────────────────────────────────────────────
function renderWeather(days) {
  const container = document.getElementById('weatherRow');
  if (!days || days.length === 0) {
    container.innerHTML = `<div class="col-12 text-muted small fst-italic">Weather data unavailable.</div>`;
    return;
  }

  const cards = days.map(d => {
    const emoji = weatherEmoji(d.description || '');
    const dateLabel = formatDate(d.forecast_date);
    const precip = d.precip_chance != null ? `${d.precip_chance}%` : '—';
    const wind = d.wind_mph != null ? `${d.wind_mph} mph` : '—';
    const hi = d.high_f != null ? `${d.high_f}°` : '—';
    const lo = d.low_f != null ? `${d.low_f}°` : '—';
    return `
      <div class="col-6 col-md-3">
        <div class="card weather-card h-100">
          <div class="card-body text-center py-2 px-2">
            <div class="weather-date small fw-semibold">${dateLabel}</div>
            <div class="weather-emoji display-6">${emoji}</div>
            <div class="weather-desc small text-muted">${escHtml(d.description || '')}</div>
            <div class="weather-temp fw-bold">${hi} / ${lo}</div>
            <div class="small mt-1">
              💨 ${wind} &nbsp; 🌧 ${precip}
            </div>
          </div>
        </div>
      </div>`;
  }).join('');

  container.innerHTML = cards;
}

function weatherEmoji(desc) {
  const d = (desc || '').toLowerCase();
  if (d.includes('thunder') || d.includes('storm')) return '⛈️';
  if (d.includes('snow') || d.includes('blizzard')) return '❄️';
  if (d.includes('rain') || d.includes('drizzle') || d.includes('shower')) return '🌧️';
  if (d.includes('fog') || d.includes('mist') || d.includes('haze')) return '🌫️';
  if (d.includes('cloud') || d.includes('overcast')) return '☁️';
  if (d.includes('partly') || d.includes('mostly')) return '⛅';
  if (d.includes('sun') || d.includes('clear') || d.includes('fair')) return '☀️';
  return '⛅';
}

// ── Player table ──────────────────────────────────────────────────────────────
function applyFilters() {
  const search = (document.getElementById('searchInput').value || '').toLowerCase().trim();
  const sort = document.getElementById('sortSelect').value;
  const filter = CURRENT_FILTER;

  let players = [...ALL_PLAYERS];

  // Filter by recommendation
  if (filter !== 'all') {
    players = players.filter(p => p.recommendation === filter);
  }

  // Search by player name
  if (search) {
    players = players.filter(p => (p.player_name || '').toLowerCase().includes(search));
  }

  // Sort
  players.sort((a, b) => {
    if (sort === 'player_name') {
      return (a.player_name || '').localeCompare(b.player_name || '');
    }
    if (sort === 'edge_top10') {
      return sortNullsLast(b.edge_top10, a.edge_top10);
    }
    if (sort === 'dg_win_prob') {
      return sortNullsLast(b.dg_win_prob, a.dg_win_prob);
    }
    if (sort === 'sg_total') {
      return sortNullsLast(b.sg_total, a.sg_total);
    }
    return 0;
  });

  renderPlayers(players);
}

function sortNullsLast(a, b) {
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  return a - b;
}

function setFilter(value, btn) {
  CURRENT_FILTER = value;
  document.querySelectorAll('#filterBtns .btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}

function renderPlayers(players) {
  const tbody = document.getElementById('playerTableBody');

  if (!players || players.length === 0) {
    tbody.innerHTML = `
      <tr><td colspan="16" class="text-center text-muted py-5">
        No players found — try adjusting filters or click <strong>Refresh Data</strong>.
      </td></tr>`;
    return;
  }

  const rows = players.map((p, idx) => {
    const rowId = `player-${idx}`;
    const blurbId = `blurb-${idx}`;

    const rec = p.recommendation || 'No Data';
    const recBadge = buildRecBadge(rec);

    const edgeVal = p.edge_top10 ?? p.edge_win;
    const edgeLabel = p.edge_top10 != null ? '' : ' title="Win edge (no top10 market)"';
    const edgeDisplay = edgeVal != null
      ? `<span class="${edgeBadgeClass(rec)} badge"${edgeLabel}>${(edgeVal * 100).toFixed(1)}pp</span>`
      : `<span class="badge bg-secondary">—</span>`;

    const courseFit = formatCourseFit(p.course_history_sg);
    const formDisplay = formIndicator(p.recent_form_sg);

    return `
      <tr class="player-row" id="${rowId}" style="cursor:pointer" onclick="toggleBlurb('${blurbId}', '${rowId}')">
        <td class="fw-semibold">${escHtml(p.player_name || '—')}</td>
        <td><span class="text-muted small">${escHtml(p.country || '—')}</span></td>
        <td>${formatProb(p.dg_win_prob)}</td>
        <td>${formatProb(p.dg_top10_prob)}</td>
        <td class="font-monospace small">${formatAmerican(p.odds_win_american)}</td>
        <td class="font-monospace small">${formatAmerican(p.odds_top10_american)}</td>
        <td>${edgeDisplay}</td>
        <td>${formatScoringAvg(p.sg_total)}</td>
        <td>${formatDrivingDist(p.sg_ott)}</td>
        <td>${formatGIR(p.sg_app)}</td>
        <td>${formatBirdies(p.sg_atg)}</td>
        <td>${formatPutts(p.sg_putt)}</td>
        <td>${courseFit}</td>
        <td>${formDisplay}</td>
        <td>${recBadge}</td>
        <td><span class="expander-icon small text-muted">▶</span></td>
      </tr>
      <tr class="blurb-row d-none" id="${blurbId}">
        <td colspan="16">
          <div class="blurb-content px-2 py-2 text-muted fst-italic small">
            ${escHtml(p.blurb || 'No analysis available.')}
          </div>
        </td>
      </tr>`;
  }).join('');

  tbody.innerHTML = rows;
}

function toggleBlurb(blurbId, rowId) {
  const blurbRow = document.getElementById(blurbId);
  const playerRow = document.getElementById(rowId);
  const icon = playerRow.querySelector('.expander-icon');
  if (!blurbRow) return;
  const hidden = blurbRow.classList.contains('d-none');
  blurbRow.classList.toggle('d-none', !hidden);
  if (icon) icon.textContent = hidden ? '▼' : '▶';
}

// ── Format helpers ────────────────────────────────────────────────────────────
function formatProb(p) {
  if (p === null || p === undefined) return '<span class="text-muted">—</span>';
  return `${(p * 100).toFixed(1)}%`;
}

function formatAmerican(n) {
  if (n === null || n === undefined) return '<span class="text-muted">N/A</span>';
  return n >= 0 ? `+${n}` : `${n}`;
}

function formatSGColored(n) {
  if (n === null || n === undefined) return '<span class="text-muted">—</span>';
  const cls = n > 0.3 ? 'text-success' : (n >= 0 ? 'text-warning' : 'text-danger');
  const sign = n >= 0 ? '+' : '';
  return `<span class="${cls}">${sign}${n.toFixed(2)}</span>`;
}

// ── ESPN stat formatters ──────────────────────────────────────────────────────

function formatScoringAvg(n) {
  // Lower is better. Shade green if under 70, red if over 72.
  if (n === null || n === undefined) return '<span class="text-muted">—</span>';
  const cls = n < 70.0 ? 'text-success' : (n < 72.0 ? 'text-warning' : 'text-danger');
  return `<span class="${cls}">${n.toFixed(1)}</span>`;
}

function formatDrivingDist(n) {
  // Driving distance yards — higher is better contextually, neutral display.
  if (n === null || n === undefined) return '<span class="text-muted">—</span>';
  return `<span class="text-secondary">${Math.round(n)}</span>`;
}

function formatGIR(n) {
  // GIR% — higher is better. Green if >= 68%, red if < 60%.
  if (n === null || n === undefined) return '<span class="text-muted">—</span>';
  const cls = n >= 68.0 ? 'text-success' : (n >= 60.0 ? 'text-warning' : 'text-danger');
  return `<span class="${cls}">${n.toFixed(1)}%</span>`;
}

function formatBirdies(n) {
  // Birdies per round — higher is better. Green if >= 4.0.
  if (n === null || n === undefined) return '<span class="text-muted">—</span>';
  const cls = n >= 4.0 ? 'text-success' : (n >= 3.0 ? 'text-warning' : 'text-danger');
  return `<span class="${cls}">${n.toFixed(1)}</span>`;
}

function formatPutts(n) {
  // Putts per hole — lower is better. Green if <= 1.72, red if > 1.80.
  if (n === null || n === undefined) return '<span class="text-muted">—</span>';
  const cls = n <= 1.72 ? 'text-success' : (n <= 1.80 ? 'text-warning' : 'text-danger');
  return `<span class="${cls}">${n.toFixed(2)}</span>`;
}

function formIndicator(sg) {
  if (sg === null || sg === undefined) return '<span class="text-muted">—</span>';
  if (sg > 0.5) return `<span class="text-success fw-bold" title="Hot: ${sg.toFixed(2)} strokes/rnd better than season">↑ Hot</span>`;
  if (sg > 0.2) return `<span class="text-success" title="Trending up: ${sg.toFixed(2)} strokes/rnd better than season">↑</span>`;
  if (sg < -0.5) return `<span class="text-danger fw-bold" title="Cold: ${Math.abs(sg).toFixed(2)} strokes/rnd worse than season">↓ Cold</span>`;
  if (sg < -0.2) return `<span class="text-danger" title="Trending down: ${Math.abs(sg).toFixed(2)} strokes/rnd worse than season">↓</span>`;
  return `<span class="text-secondary" title="Neutral form: ${sg.toFixed(2)} vs season avg">→</span>`;
}

function formatCourseFit(score) {
  if (score === null || score === undefined) return '<span class="text-muted">—</span>';
  // score is a deviation from winner profile — positive = good fit
  if (score > 0.5) return `<span class="text-success fw-bold" title="Strong course fit (${score.toFixed(2)})">A+</span>`;
  if (score > 0.2) return `<span class="text-success" title="Good course fit (${score.toFixed(2)})">A</span>`;
  if (score > -0.2) return `<span class="text-secondary" title="Average course fit (${score.toFixed(2)})">B</span>`;
  if (score > -0.5) return `<span class="text-warning" title="Below-avg course fit (${score.toFixed(2)})">C</span>`;
  return `<span class="text-danger" title="Poor course fit (${score.toFixed(2)})">D</span>`;
}

function buildRecBadge(rec) {
  const cls = recBadgeClass(rec);
  return `<span class="badge ${cls}">${escHtml(rec)}</span>`;
}

function recBadgeClass(rec) {
  switch (rec) {
    case 'Strong Value': return 'bg-success';
    case 'Value':        return 'bg-info text-dark';
    case 'Fair':         return 'bg-secondary';
    case 'Fade':         return 'bg-danger';
    default:             return 'bg-dark';
  }
}

function edgeBadgeClass(rec) {
  switch (rec) {
    case 'Strong Value': return 'bg-success';
    case 'Value':        return 'bg-info text-dark';
    case 'Fair':         return 'bg-secondary';
    case 'Fade':         return 'bg-danger';
    default:             return 'bg-secondary';
  }
}

function formatTimestamp(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
    });
  } catch (_) {
    return iso;
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  try {
    // dateStr like "2025-05-15"
    const [y, m, d] = dateStr.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  } catch (_) {
    return dateStr;
  }
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Refresh ───────────────────────────────────────────────────────────────────
async function doRefresh() {
  const btn = document.getElementById('refreshBtn');
  const btnText = document.getElementById('refreshBtnText');
  const spinner = document.getElementById('refreshSpinner');

  btn.disabled = true;
  btnText.textContent = 'Refreshing…';
  spinner.classList.remove('d-none');

  try {
    const res = await fetch('/api/refresh', { method: 'POST' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();

    if (result.warnings && result.warnings.length > 0) {
      showAlert(
        `Refresh complete with warnings:<br>• ${result.warnings.join('<br>• ')}`,
        'warning'
      );
    } else {
      showAlert('Data refreshed successfully.', 'success', 3000);
    }

    // Re-fetch and re-render
    await fetchData();
  } catch (err) {
    showAlert(`Refresh failed: ${err.message}`, 'danger');
  } finally {
    btn.disabled = false;
    btnText.textContent = 'Refresh Data';
    spinner.classList.add('d-none');
  }
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
  if (HISTORY_LOADED) return;

  const accordion = document.getElementById('historyAccordion');
  const placeholder = document.getElementById('historyPlaceholder');

  try {
    const res = await fetch('/api/history');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const history = await res.json();

    if (placeholder) placeholder.remove();

    if (!history || history.length === 0) {
      accordion.innerHTML = '<div class="text-muted small">No historical picks recorded yet.</div>';
      HISTORY_LOADED = true;
      return;
    }

    // ── Group by event_id, sorted most-recent first ──────────────────────────
    const groups = {};
    for (const row of history) {
      const key = row.event_id || row.week_label;
      if (!groups[key]) {
        groups[key] = {
          event_name: row.event_name,
          week_label: row.week_label,
          rows: [],
        };
      }
      groups[key].rows.push(row);
    }

    // Sort groups newest first by week_label
    const sortedGroups = Object.values(groups).sort((a, b) => {
      return (b.week_label || '').localeCompare(a.week_label || '');
    });

    // ── Overall stats bar ────────────────────────────────────────────────────
    const allRows = history;
    const totalWeeks = sortedGroups.length;
    const totalPicks = allRows.length;
    const resolvedRows = allRows.filter(r => r.outcome_hit !== null && r.outcome_hit !== undefined);
    const hits = resolvedRows.filter(r => r.outcome_hit === 1).length;
    const hitRate = resolvedRows.length > 0
      ? ((hits / resolvedRows.length) * 100).toFixed(1)
      : null;
    const edgeRows = allRows.filter(r => r.edge != null);
    const avgEdge = edgeRows.length > 0
      ? edgeRows.reduce((s, r) => s + r.edge, 0) / edgeRows.length
      : null;

    const statsHtml = `
      <div class="d-flex flex-wrap gap-3 mb-3 p-3 rounded border small">
        <div class="text-center">
          <div class="fw-bold fs-5">${totalWeeks}</div>
          <div class="text-muted">Weeks</div>
        </div>
        <div class="text-center">
          <div class="fw-bold fs-5">${totalPicks}</div>
          <div class="text-muted">Total Picks</div>
        </div>
        <div class="text-center">
          <div class="fw-bold fs-5 ${hitRate !== null ? (parseFloat(hitRate) >= 30 ? 'text-success' : 'text-danger') : ''}">${hitRate !== null ? hitRate + '%' : '—'}</div>
          <div class="text-muted">Hit Rate${resolvedRows.length < totalPicks ? ' <span title="Some results still pending" class=\'text-warning\'>*</span>' : ''}</div>
        </div>
        <div class="text-center">
          <div class="fw-bold fs-5 ${avgEdge !== null ? (avgEdge > 0 ? 'text-success' : 'text-danger') : ''}">${avgEdge !== null ? (avgEdge * 100).toFixed(1) + 'pp' : '—'}</div>
          <div class="text-muted">Avg Edge</div>
        </div>
        ${resolvedRows.length < totalPicks ? '<div class="text-muted fst-italic align-self-end">* Pending results update automatically on refresh.</div>' : ''}
      </div>`;

    // ── Per-week accordion panels ────────────────────────────────────────────
    const panels = sortedGroups.map((g, idx) => {
      const panelId  = `hist-panel-${idx}`;
      const collapseId = `hist-collapse-${idx}`;

      const gResolved = g.rows.filter(r => r.outcome_hit !== null && r.outcome_hit !== undefined);
      const gHits = gResolved.filter(r => r.outcome_hit === 1).length;
      const gHitRate = gResolved.length > 0
        ? ((gHits / gResolved.length) * 100).toFixed(0) + '%'
        : null;

      // Header summary
      const summaryParts = [`${g.rows.length} pick${g.rows.length !== 1 ? 's' : ''}`];
      if (gResolved.length > 0) {
        summaryParts.push(`${gHits} hit${gHits !== 1 ? 's' : ''} — ${gHitRate}`);
      } else {
        summaryParts.push('Pending');
      }
      const summary = summaryParts.join(', ');

      const tableRows = g.rows.map(r => {
        let outcomeBadge;
        if (r.outcome_hit === 1) {
          outcomeBadge = '<span class="badge bg-success">&#10003; Hit</span>';
        } else if (r.outcome_hit === 0) {
          outcomeBadge = '<span class="badge bg-danger">&#10007; Miss</span>';
        } else {
          outcomeBadge = '<span class="badge bg-secondary">Pending</span>';
        }

        const recBadge = buildRecBadge(r.recommendation || '—');
        const finishDisplay = r.finish_position != null ? `#${r.finish_position}` : '—';
        const edgeDisplay = r.edge != null ? `${(r.edge * 100).toFixed(1)}pp` : '—';

        return `
          <tr>
            <td class="fw-semibold">${escHtml(r.player_name || '—')}</td>
            <td>${recBadge}</td>
            <td>${formatProb(r.model_prob)}</td>
            <td>${formatProb(r.market_prob)}</td>
            <td class="font-monospace small">${edgeDisplay}</td>
            <td class="font-monospace">${finishDisplay}</td>
            <td>${outcomeBadge}</td>
          </tr>`;
      }).join('');

      // Get event_id from first row
      const eventId = g.rows[0] ? (g.rows[0].event_id || '') : '';

      return `
        <div class="accordion-item" id="${panelId}">
          <h2 class="accordion-header">
            <button class="accordion-button collapsed py-2" type="button"
                    data-bs-toggle="collapse" data-bs-target="#${collapseId}"
                    onclick="loadTournamentDetail('${escHtml(eventId)}', '${collapseId}')">
              <span class="fw-semibold me-2">${escHtml(g.event_name || 'Tournament')}</span>
              <span class="text-muted small me-2">${escHtml(g.week_label || '')}</span>
              <span class="text-muted small fst-italic">${escHtml(summary)}</span>
            </button>
          </h2>
          <div id="${collapseId}" class="accordion-collapse collapse">
            <div class="accordion-body p-2" id="${collapseId}-body">
              <div class="text-muted small fst-italic p-2">Loading tournament detail…</div>
            </div>
          </div>
        </div>`;
    }).join('');

    // Insert stats bar before accordion
    accordion.insertAdjacentHTML('beforebegin', statsHtml);
    accordion.innerHTML = panels;
    HISTORY_LOADED = true;

  } catch (err) {
    accordion.innerHTML = `<div class="text-danger small">Failed to load history: ${err.message}</div>`;
  }
}

// ── Tournament detail (per-event full field) ──────────────────────────────────
async function loadTournamentDetail(eventId, collapseId) {
  const bodyEl = document.getElementById(`${collapseId}-body`);
  if (!bodyEl) return;

  // Don't re-fetch if already loaded
  if (TOURNAMENT_DETAIL_CACHE[eventId]) {
    renderTournamentDetail(bodyEl, TOURNAMENT_DETAIL_CACHE[eventId]);
    return;
  }

  if (!eventId) {
    bodyEl.innerHTML = '<div class="text-muted small p-2">No detail available.</div>';
    return;
  }

  try {
    const res = await fetch(`/api/tournament/${encodeURIComponent(eventId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();
    TOURNAMENT_DETAIL_CACHE[eventId] = rows;
    renderTournamentDetail(bodyEl, rows);
  } catch (err) {
    bodyEl.innerHTML = `<div class="text-danger small p-2">Failed to load detail: ${err.message}</div>`;
  }
}

function renderTournamentDetail(container, rows) {
  if (!rows || rows.length === 0) {
    container.innerHTML = '<div class="text-muted small p-2">No data available for this tournament.</div>';
    return;
  }

  const picks = rows.filter(r => r.is_pick === 1);
  const fullField = rows; // all rows, sorted by model_rank from API

  function outcomeCell(r) {
    if (r.finish_position == null) return '<span class="badge bg-secondary">Pending</span>';
    if (r.finish_position <= 10) return '<span class="badge bg-success">&#10003; Hit</span>';
    return '<span class="badge bg-danger">&#10007; Miss</span>';
  }

  function rankDeltaCell(r) {
    if (r.finish_position == null || r.model_rank == null) return '<span class="text-muted">—</span>';
    const delta = r.model_rank - r.finish_position;
    if (delta > 0) return `<span class="text-success">+${delta}</span>`;
    if (delta < 0) return `<span class="text-danger">${delta}</span>`;
    return '<span class="text-secondary">0</span>';
  }

  function buildTable(tableRows) {
    const trs = tableRows.map(r => `
      <tr>
        <td class="fw-semibold">${escHtml(r.player_name || '—')}</td>
        <td class="text-center font-monospace small">#${r.model_rank || '—'}</td>
        <td>${formatProb(r.model_win_prob)}</td>
        <td class="text-center font-monospace">${r.finish_position != null ? '#' + r.finish_position : '—'}</td>
        <td class="text-center">${rankDeltaCell(r)}</td>
        <td>${outcomeCell(r)}</td>
      </tr>`).join('');

    return `
      <div class="table-responsive">
        <table class="table table-sm table-hover mb-0">
          <thead>
            <tr>
              <th>Player</th>
              <th class="text-center" title="Model's win probability rank">Model Rank</th>
              <th>Model Win%</th>
              <th class="text-center">Finish</th>
              <th class="text-center" title="Model rank minus finish position (positive = finished better than predicted)">Rank Delta</th>
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>${trs}</tbody>
        </table>
      </div>`;
  }

  // Picks section
  const picksHtml = picks.length > 0
    ? `<div class="mb-3">
         <div class="fw-semibold small mb-1 text-muted text-uppercase" style="letter-spacing:.05em">Model Picks (Top 20)</div>
         ${buildTable(picks)}
       </div>`
    : '';

  // Full field (collapsed)
  const fullFieldId = `ff-${Math.random().toString(36).slice(2)}`;
  const fullFieldHtml = `
    <div>
      <button class="btn btn-sm btn-outline-secondary mb-2" type="button"
              onclick="
                var el=document.getElementById('${fullFieldId}');
                var btn=this;
                if(el.style.display==='none'){el.style.display='';btn.textContent='Hide full field ▲';}
                else{el.style.display='none';btn.textContent='Show full field ▶';}
              ">
        Show full field ▶
      </button>
      <div id="${fullFieldId}" style="display:none">
        ${buildTable(fullField)}
      </div>
    </div>`;

  container.innerHTML = picksHtml + fullFieldHtml;
}

// ── Player Leaderboard ────────────────────────────────────────────────────────
async function loadLeaderboard() {
  if (LEADERBOARD_LOADED) return;

  const container = document.getElementById('leaderboardContainer');
  const placeholder = document.getElementById('leaderboardPlaceholder');

  try {
    const res = await fetch('/api/leaderboard');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();

    if (placeholder) placeholder.remove();

    if (!rows || rows.length === 0) {
      container.innerHTML = '<div class="text-muted small">No leaderboard data yet — run a refresh to populate.</div>';
      LEADERBOARD_LOADED = true;
      return;
    }

    const tableRows = rows.map(r => {
      const hitRateDisplay = r.hit_rate != null
        ? `<span class="${r.hit_rate >= 30 ? 'text-success' : 'text-danger'}">${r.hit_rate}%</span>`
        : '<span class="text-muted">—</span>';

      let rdDisplay = '<span class="text-muted">—</span>';
      if (r.rank_delta != null) {
        const cls = r.rank_delta > 5 ? 'text-success fw-bold'
                  : r.rank_delta > 0 ? 'text-success'
                  : r.rank_delta < -5 ? 'text-danger fw-bold'
                  : r.rank_delta < 0 ? 'text-danger'
                  : 'text-secondary';
        const sign = r.rank_delta > 0 ? '+' : '';
        rdDisplay = `<span class="${cls}" title="Avg model rank minus avg finish — positive means finished better than model predicted">${sign}${r.rank_delta}</span>`;
      }

      return `
        <tr>
          <td class="fw-semibold">${escHtml(r.player_name || '—')}</td>
          <td class="text-center">${r.tournaments || 0}</td>
          <td class="text-center">${r.picks || 0}</td>
          <td class="text-center">${r.hits || 0}</td>
          <td class="text-center">${hitRateDisplay}</td>
          <td class="text-center font-monospace small">${r.avg_model_rank != null ? r.avg_model_rank : '—'}</td>
          <td class="text-center font-monospace small">${r.avg_finish_rank != null ? r.avg_finish_rank : '—'}</td>
          <td class="text-center">${rdDisplay}</td>
        </tr>`;
    }).join('');

    container.innerHTML = `
      <div class="table-responsive-wrapper">
        <div class="table-responsive">
          <table class="table table-sm table-hover align-middle" style="font-size:0.85rem">
            <thead>
              <tr>
                <th>Player</th>
                <th class="text-center" title="Tournaments tracked">Events</th>
                <th class="text-center" title="Times in model top-20">Picks</th>
                <th class="text-center" title="Times picked and finished top-10">Hits</th>
                <th class="text-center" title="Hit rate (hits / picks)">Hit Rate</th>
                <th class="text-center" title="Average model win probability rank">Avg Model Rank</th>
                <th class="text-center" title="Average actual finish position">Avg Finish</th>
                <th class="text-center" title="Avg model rank minus avg finish. Positive = finished better than predicted.">Rank Delta</th>
              </tr>
            </thead>
            <tbody>${tableRows}</tbody>
          </table>
        </div>
      </div>
      <div class="text-muted small mt-2 fst-italic">
        Rank Delta: model rank minus finish position — positive means the player finished better than the model predicted.
        Based on retroactive model runs using current season stats.
      </div>`;

    LEADERBOARD_LOADED = true;

  } catch (err) {
    container.innerHTML = `<div class="text-danger small">Failed to load leaderboard: ${err.message}</div>`;
  }
}

// ── Theme toggle ──────────────────────────────────────────────────────────────
function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-bs-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-bs-theme', next);
  document.getElementById('themeToggle').textContent = next === 'dark' ? '🌙' : '☀️';
}

// ── Alert helper ──────────────────────────────────────────────────────────────
function showAlert(msg, type = 'info', autoDismissMs = 0) {
  const alertArea = document.getElementById('alertArea');
  const id = `alert-${Date.now()}`;
  const html = `
    <div class="alert alert-${type} alert-dismissible fade show py-2" role="alert" id="${id}">
      ${msg}
      <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>`;
  alertArea.insertAdjacentHTML('afterbegin', html);

  if (autoDismissMs > 0) {
    setTimeout(() => {
      const el = document.getElementById(id);
      if (el) {
        const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
        bsAlert.close();
      }
    }, autoDismissMs);
  }
}

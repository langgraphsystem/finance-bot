/* =========================================================================
   Trackers Module — 2026 Design
   ========================================================================= */

'use strict';

// ─── Tracker metadata ────────────────────────────────────────────────────────
const TRACKER_TYPES = [
  { type: 'mood',       emoji: '😊', label: 'Mood',       desc: 'Daily emotional check-in' },
  { type: 'habit',      emoji: '🔥', label: 'Habit',      desc: 'Build streaks & routines' },
  { type: 'water',      emoji: '💧', label: 'Water',      desc: 'Hydration glasses tracker' },
  { type: 'sleep',      emoji: '🌙', label: 'Sleep',      desc: 'Hours of sleep each night' },
  { type: 'weight',     emoji: '⚖️', label: 'Weight',     desc: 'Body weight over time' },
  { type: 'workout',    emoji: '💪', label: 'Workout',    desc: 'Exercise sessions & sets' },
  { type: 'nutrition',  emoji: '🥗', label: 'Nutrition',  desc: 'Calories & macros log' },
  { type: 'gratitude',  emoji: '🙏', label: 'Gratitude',  desc: 'Daily thankfulness journal' },
  { type: 'medication', emoji: '💊', label: 'Medication', desc: 'Pills & dose schedule' },
  { type: 'custom',     emoji: '✨', label: 'Custom',     desc: 'Track anything you want' },
];

const MOOD_FACES = [
  { score: 1, emoji: '😭', label: 'Awful'  },
  { score: 2, emoji: '😢', label: 'Bad'    },
  { score: 3, emoji: '😔', label: 'Meh'    },
  { score: 4, emoji: '🙁', label: 'Low'    },
  { score: 5, emoji: '😐', label: 'Okay'   },
  { score: 6, emoji: '🙂', label: 'Fine'   },
  { score: 7, emoji: '😊', label: 'Good'   },
  { score: 8, emoji: '😄', label: 'Great'  },
  { score: 9, emoji: '🤩', label: 'Amazing'},
  { score: 10, emoji: '🥳', label: 'Best'  },
];

// ─── State ───────────────────────────────────────────────────────────────────
let _activeTrackerId = null;   // currently open tracker detail
let _trackers = [];            // cached list

// ─── Helpers ─────────────────────────────────────────────────────────────────
function _todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function _daysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function _shortDate(iso) {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function _getGradSvg(type) {
  const grads = {
    mood:       ['#c084fc','#f472b6'],
    habit:      ['#fb923c','#fbbf24'],
    water:      ['#22d3ee','#3b82f6'],
    sleep:      ['#818cf8','#6366f1'],
    weight:     ['#34d399','#059669'],
    workout:    ['#f87171','#ef4444'],
    nutrition:  ['#fbbf24','#f59e0b'],
    gratitude:  ['#fb7185','#f59e0b'],
    medication: ['#2dd4bf','#0d9488'],
    custom:     ['#a78bfa','#7c3aed'],
  };
  const [a, b] = grads[type] || ['#a78bfa','#7c3aed'];
  return `<defs>
    <linearGradient id="grad-${type}" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="${a}"/>
      <stop offset="100%" stop-color="${b}"/>
    </linearGradient>
  </defs>`;
}

// ─── Render Trackers List Page ────────────────────────────────────────────────
async function renderTrackers(content) {
  content.innerHTML = spinner();

  try {
    _trackers = await get('/trackers');
  } catch (e) {
    content.innerHTML = `<div class="error-state" style="padding:40px 20px;text-align:center;color:var(--hint)">${e.message}</div>`;
    return;
  }

  if (_trackers.length === 0) {
    content.innerHTML = _renderTrackersEmpty();
    return;
  }

  content.innerHTML = `
    <div class="trackers-header">
      <h2>My Trackers</h2>
      <button class="btn-new-tracker" onclick="openNewTrackerModal()">＋ New</button>
    </div>
    <div class="tracker-grid">
      ${_trackers.map(_renderTrackerCard).join('')}
    </div>
  `;
}

function _renderTrackersEmpty() {
  return `
    <div class="tracker-empty">
      <span class="tracker-empty-icon">📊</span>
      <h3>No Trackers Yet</h3>
      <p>Track your mood, habits, water, sleep and more — beautifully.</p>
      <button class="btn-primary" onclick="openNewTrackerModal()" style="margin:0 auto">＋ Create First Tracker</button>
    </div>
  `;
}

function _renderTrackerCard(t) {
  const streakHtml = t.streak > 0
    ? `<div class="tracker-streak"><span class="streak-fire">🔥</span> ${t.streak}d</div>`
    : '';
  const btnLabel = t.today_done ? '✓ Logged today' : `Log ${t.emoji}`;
  return `
    <div class="tracker-card" data-type="${t.tracker_type}" onclick="openTrackerDetail('${t.id}')">
      <span class="tracker-card-emoji">${t.emoji}</span>
      <div class="tracker-card-name">${t.name}</div>
      <div class="tracker-card-meta">${_typeLabel(t.tracker_type)}</div>
      ${streakHtml}
      <button
        class="tracker-today-btn ${t.today_done ? 'done' : ''}"
        data-type="${t.tracker_type}"
        onclick="event.stopPropagation(); quickLog('${t.id}', '${t.tracker_type}')"
      >${btnLabel}</button>
    </div>
  `;
}

function _typeLabel(type) {
  const t = TRACKER_TYPES.find(x => x.type === type);
  return t ? t.desc : type;
}

// ─── Tracker Detail Page ──────────────────────────────────────────────────────
async function openTrackerDetail(trackerId) {
  _activeTrackerId = trackerId;
  const tracker = _trackers.find(t => t.id === trackerId);
  if (!tracker) return;

  document.getElementById('screen-title').textContent = tracker.name;

  const content = document.getElementById('content');
  content.innerHTML = spinner();

  // Load entries (30 days)
  let entries = [];
  try {
    entries = await get(`/trackers/${trackerId}/entries?days=30`);
  } catch (_) {}

  content.innerHTML = _renderTrackerDetail(tracker, entries);

  // Animate ring if applicable
  _animateRing(tracker, entries);
}

function _renderTrackerDetail(tracker, entries) {
  const today = _todayISO();
  const entryDates = new Set(entries.map(e => e.date));
  const totalEntries = entries.length;
  const streak = tracker.streak;

  // Compute last value for display
  const lastEntry = entries.length ? entries[entries.length - 1] : null;
  const lastVal = lastEntry?.value ?? '—';
  const unit = tracker.config?.unit || '';

  // Stats
  const statsHtml = `
    <div class="tracker-stats-row">
      <div class="tracker-stat-box">
        <div class="tracker-stat-val">${streak > 0 ? `<span class="streak-fire">🔥</span>${streak}` : '0'}</div>
        <div class="tracker-stat-lbl">Day streak</div>
      </div>
      <div class="tracker-stat-box">
        <div class="tracker-stat-val">${totalEntries}</div>
        <div class="tracker-stat-lbl">Total logs</div>
      </div>
      <div class="tracker-stat-box">
        <div class="tracker-stat-val">${lastVal !== '—' ? lastVal : '—'}<small style="font-size:11px;font-weight:500;color:var(--hint)"> ${lastVal !== '—' ? unit : ''}</small></div>
        <div class="tracker-stat-lbl">Last logged</div>
      </div>
    </div>
  `;

  // Heatmap (30 cells, oldest→newest, left→right)
  const cells = Array.from({ length: 30 }, (_, i) => {
    const iso = _daysAgo(29 - i);
    const has = entryDates.has(iso);
    const isToday = iso === today;
    return `<div class="heatmap-cell ${has ? 'has-entry' : ''} ${isToday ? 'today' : ''}" data-type="${tracker.tracker_type}" title="${_shortDate(iso)}"></div>`;
  }).join('');

  const heatmapHtml = `
    <div class="tracker-heatmap-section">
      <div class="tracker-heatmap-title">Last 30 Days</div>
      <div class="tracker-heatmap">${cells}</div>
    </div>
  `;

  // Entries list (recent 10)
  const recentEntries = [...entries].reverse().slice(0, 10);
  const entriesHtml = recentEntries.length ? `
    <div class="tracker-entries-section">
      <div class="tracker-entries-title">Recent Entries</div>
      ${recentEntries.map(e => _renderEntryRow(e, tracker)).join('')}
    </div>
  ` : '';

  const todayDone = entryDates.has(today);

  return `
    <!-- Hero -->
    <div class="tracker-detail-hero" data-type="${tracker.tracker_type}">
      <span class="tracker-detail-hero-emoji">${tracker.emoji}</span>
      <div class="tracker-detail-hero-name">${tracker.name}</div>
      <div class="tracker-detail-hero-meta">${_typeLabel(tracker.tracker_type)}</div>
    </div>

    ${statsHtml}
    ${heatmapHtml}

    <!-- Log button -->
    <button
      class="tracker-log-btn"
      data-type="${tracker.tracker_type}"
      onclick="openLogModal('${tracker.id}', '${tracker.tracker_type}')"
      ${todayDone && tracker.tracker_type === 'habit' ? 'disabled style="opacity:.5"' : ''}
    >
      ${todayDone ? '＋ Log Again' : `＋ Log ${tracker.emoji} Today`}
    </button>

    ${entriesHtml}

    <!-- Delete -->
    <div style="padding:0 16px 100px;text-align:center">
      <button class="btn-ghost" onclick="confirmDeleteTracker('${tracker.id}')" style="color:var(--destructive);font-size:13px">Delete Tracker</button>
    </div>
  `;
}

function _renderEntryRow(entry, tracker) {
  const valDisplay = _formatEntryValue(entry, tracker);
  return `
    <div class="tracker-entry-item">
      <div class="tracker-entry-dot" data-type="${tracker.tracker_type}"></div>
      <div class="tracker-entry-date">${_shortDate(entry.date)}</div>
      ${entry.note ? `<div class="tracker-entry-note">${entry.note}</div>` : ''}
      <div class="tracker-entry-val">${valDisplay}</div>
    </div>
  `;
}

function _formatEntryValue(entry, tracker) {
  const unit = tracker.config?.unit || '';
  if (tracker.tracker_type === 'mood') {
    const face = MOOD_FACES.find(f => f.score === entry.value);
    return face ? `${face.emoji} ${entry.value}` : entry.value;
  }
  if (tracker.tracker_type === 'habit') return entry.value ? '✅ Done' : '—';
  if (tracker.tracker_type === 'gratitude') return entry.data?.items?.length ? `${entry.data.items.length} items` : '✍️';
  if (entry.value != null) return `${entry.value} ${unit}`;
  return '—';
}

// ─── Ring Animation ──────────────────────────────────────────────────────────
function _animateRing(tracker, entries) {
  // Not used currently — placeholder for future ring widgets in detail
}

// ─── Quick Log (from card button) ────────────────────────────────────────────
async function quickLog(trackerId, trackerType) {
  // For habit: just log immediately
  if (trackerType === 'habit') {
    try {
      await post(`/trackers/${trackerId}/entries`, { date: _todayISO(), value: 1 });
      toast('✅ Logged!');
      haptic('success');
      await renderTrackers(document.getElementById('content'));
    } catch (e) { toast(e.message); }
    return;
  }
  // For others: open proper log modal
  openLogModal(trackerId, trackerType);
}

// ─── Log Modal ────────────────────────────────────────────────────────────────
function openLogModal(trackerId, trackerType) {
  const tracker = _trackers.find(t => t.id === trackerId);
  const name = tracker?.name || trackerType;
  const emoji = tracker?.emoji || '📊';
  const unit = tracker?.config?.unit || 'times';
  const goal = tracker?.config?.goal || 1;

  let bodyHtml = '';

  if (trackerType === 'mood') {
    bodyHtml = `
      <div class="mood-picker">
        ${MOOD_FACES.map(f => `
          <div class="mood-face" data-score="${f.score}" onclick="_selectMood(${f.score}, this)">
            <span class="mood-face-emoji">${f.emoji}</span>
            <span class="mood-face-label">${f.label}</span>
          </div>
        `).join('')}
      </div>
      <textarea id="log-note" placeholder="How are you feeling? (optional)" style="width:100%;padding:12px;border-radius:14px;border:1px solid var(--section-sep);background:var(--bg2);font-family:inherit;font-size:14px;color:var(--text);resize:none;height:72px;outline:none;margin-bottom:12px"></textarea>
    `;

  } else if (trackerType === 'water') {
    const glasses = [1, 2, 3, 4, 5, 6, 7, 8];
    bodyHtml = `
      <p style="font-size:13px;color:var(--hint);margin-bottom:10px">How many glasses today?</p>
      <div class="water-glasses">
        ${glasses.map(g => `
          <div class="water-glass" data-val="${g}" onclick="_selectWater(${g}, this)">💧</div>
        `).join('')}
      </div>
      <textarea id="log-note" placeholder="Note (optional)" style="width:100%;padding:12px;border-radius:14px;border:1px solid var(--section-sep);background:var(--bg2);font-family:inherit;font-size:14px;color:var(--text);resize:none;height:60px;outline:none;margin-bottom:12px"></textarea>
    `;

  } else if (trackerType === 'gratitude') {
    bodyHtml = `
      <p style="font-size:13px;color:var(--hint);margin-bottom:10px">What are you grateful for today?</p>
      <div class="gratitude-cards">
        <input class="gratitude-card-input" id="grat-1" placeholder="1. I'm grateful for..." />
        <input class="gratitude-card-input" id="grat-2" placeholder="2. I appreciate..." />
        <input class="gratitude-card-input" id="grat-3" placeholder="3. Today was good because..." />
      </div>
    `;

  } else {
    // Generic stepper (sleep hours, weight kg, workout sessions, nutrition kcal, medication, custom)
    bodyHtml = `
      <div class="value-stepper">
        <button class="stepper-btn" onclick="_stepVal(-1)">−</button>
        <div>
          <div class="stepper-val" id="stepper-display">${trackerType === 'weight' ? '70' : goal}</div>
          <div class="stepper-unit">${unit}</div>
        </div>
        <button class="stepper-btn" onclick="_stepVal(1)">＋</button>
      </div>
      <textarea id="log-note" placeholder="Note (optional)" style="width:100%;padding:12px;border-radius:14px;border:1px solid var(--section-sep);background:var(--bg2);font-family:inherit;font-size:14px;color:var(--text);resize:none;height:60px;outline:none;margin-bottom:12px"></textarea>
    `;
  }

  const html = `
    <div style="padding:0 4px 4px">
      <div style="font-size:26px;margin-bottom:4px">${emoji}</div>
      <div style="font-size:18px;font-weight:700;margin-bottom:16px">${name}</div>
      ${bodyHtml}
      <button class="btn-primary" style="width:100%" onclick="_submitLog('${trackerId}', '${trackerType}')">Save Log</button>
    </div>
  `;

  openModal(html);

  // Store state for submit
  window._logState = { value: null, step: trackerType === 'sleep' ? 0.5 : 1 };
  if (trackerType === 'weight') window._logState.value = 70;
  else if (!['mood','water','gratitude'].includes(trackerType)) window._logState.value = goal;
}

window._selectMood = function(score, el) {
  document.querySelectorAll('.mood-face').forEach(f => f.classList.remove('selected'));
  el.classList.add('selected');
  window._logState.value = score;
};

window._selectWater = function(val, el) {
  document.querySelectorAll('.water-glass').forEach(g => g.classList.remove('selected'));
  el.classList.add('selected');
  window._logState.value = val;
};

window._stepVal = function(delta) {
  const step = window._logState?.step || 1;
  const cur = window._logState?.value ?? 0;
  const next = Math.max(0, Math.round((cur + delta * step) * 10) / 10);
  window._logState.value = next;
  const el = document.getElementById('stepper-display');
  if (el) el.textContent = next;
};

window._submitLog = async function(trackerId, trackerType) {
  const note = document.getElementById('log-note')?.value?.trim() || null;
  let value = window._logState?.value ?? null;
  let data = null;

  if (trackerType === 'mood' && value == null) {
    toast('Pick a mood first'); return;
  }
  if (trackerType === 'water' && value == null) {
    toast('Pick glasses count'); return;
  }
  if (trackerType === 'gratitude') {
    const items = [1,2,3].map(i => document.getElementById(`grat-${i}`)?.value?.trim()).filter(Boolean);
    if (!items.length) { toast('Add at least one item'); return; }
    data = { items };
    value = items.length;
  }

  try {
    await post(`/trackers/${trackerId}/entries`, {
      date: _todayISO(),
      value: typeof value === 'number' ? Math.round(value) : value,
      data,
      note,
    });
    closeModal();
    toast('✅ Logged!');
    haptic('success');

    // Re-render: detail or list
    if (_activeTrackerId) {
      await openTrackerDetail(trackerId);
    } else {
      await renderTrackers(document.getElementById('content'));
    }
  } catch (e) { toast(e.message); }
};

// ─── New Tracker Modal ────────────────────────────────────────────────────────
function openNewTrackerModal() {
  let selectedType = null;

  const typesHtml = TRACKER_TYPES.map(t => `
    <div class="tracker-type-option" data-type="${t.type}" onclick="_selectTrackerType('${t.type}', this)">
      <div class="tracker-type-icon">${t.emoji}</div>
      <div class="tracker-type-info">
        <strong>${t.label}</strong>
        <span>${t.desc}</span>
      </div>
    </div>
  `).join('');

  const html = `
    <div style="padding:0 4px 4px">
      <div style="font-size:18px;font-weight:700;margin-bottom:4px">New Tracker</div>
      <div style="font-size:13px;color:var(--hint);margin-bottom:16px">Choose what to track</div>

      <div class="tracker-type-grid">${typesHtml}</div>

      <div id="tracker-name-row" style="display:none;margin-top:4px">
        <input
          id="tracker-name-input"
          placeholder="Tracker name (e.g. Morning Run)"
          style="width:100%;padding:14px;border-radius:16px;border:1px solid var(--section-sep);background:var(--bg2);font-family:inherit;font-size:15px;color:var(--text);outline:none;margin-bottom:12px"
        />
        <button class="btn-primary" style="width:100%" onclick="_createTracker()">Create Tracker</button>
      </div>
    </div>
  `;

  openModal(html);
  window._newTrackerType = null;
}

window._selectTrackerType = function(type, el) {
  document.querySelectorAll('.tracker-type-option').forEach(o => o.classList.remove('selected'));
  el.classList.add('selected');
  window._newTrackerType = type;

  const nameRow = document.getElementById('tracker-name-row');
  const nameInput = document.getElementById('tracker-name-input');
  if (nameRow) nameRow.style.display = 'block';

  // Set default name from type
  const meta = TRACKER_TYPES.find(t => t.type === type);
  if (nameInput && !nameInput.value) nameInput.value = meta?.label || '';
  nameInput?.focus();
};

window._createTracker = async function() {
  const type = window._newTrackerType;
  const name = document.getElementById('tracker-name-input')?.value?.trim();
  if (!type) { toast('Pick a tracker type'); return; }
  if (!name)  { toast('Give it a name'); return; }

  const meta = TRACKER_TYPES.find(t => t.type === type);

  try {
    await post('/trackers', { tracker_type: type, name, emoji: meta?.emoji });
    closeModal();
    toast(`${meta?.emoji} ${name} created!`);
    haptic('success');
    _activeTrackerId = null;
    await renderTrackers(document.getElementById('content'));
  } catch (e) { toast(e.message); }
};

// ─── Delete Tracker ───────────────────────────────────────────────────────────
async function confirmDeleteTracker(trackerId) {
  const tracker = _trackers.find(t => t.id === trackerId);
  const html = `
    <div style="padding:0 4px 4px;text-align:center">
      <div style="font-size:40px;margin-bottom:12px">🗑️</div>
      <div style="font-size:17px;font-weight:700;margin-bottom:8px">Delete "${tracker?.name || 'tracker'}"?</div>
      <div style="font-size:14px;color:var(--hint);margin-bottom:24px">All logged entries will be lost.</div>
      <button class="btn-danger" style="width:100%;margin-bottom:10px" onclick="_deleteTracker('${trackerId}')">Delete</button>
      <button class="btn-ghost" style="width:100%" onclick="closeModal()">Cancel</button>
    </div>
  `;
  openModal(html);
}

window._deleteTracker = async function(trackerId) {
  try {
    await del(`/trackers/${trackerId}`);
    closeModal();
    toast('Tracker deleted');
    _activeTrackerId = null;
    // Return to list
    document.getElementById('screen-title').textContent = 'Trackers';
    await renderTrackers(document.getElementById('content'));
  } catch (e) { toast(e.message); }
};

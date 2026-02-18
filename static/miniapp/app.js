/* =========================================================================
   Finance Bot Mini App — app.js
   ========================================================================= */

'use strict';

// ─── Telegram WebApp init ──────────────────────────────────────────────────
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.expand();
  tg.setHeaderColor('bg_color');
  tg.ready();
}

const INIT_DATA = tg?.initData || '';

// ─── Global state ──────────────────────────────────────────────────────────
const state = {
  user: null,
  categories: [],
  currentTab: 'dashboard',
  charts: {},
  txFilter: { type: null, category: null, search: '' },
  txPage: 1,
  txTotal: 0,
  statsperiod: 'month',
};

// ─── API helpers ───────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const headers = {
    'Content-Type': 'application/json',
    'X-Telegram-Init-Data': INIT_DATA,
    ...opts.headers,
  };
  const r = await fetch('/api' + path, { ...opts, headers });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || 'API error');
  }
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('text/csv')) return r;
  return r.json();
}

const get  = (p)       => api(p);
const post = (p, body) => api(p, { method: 'POST', body: JSON.stringify(body) });
const put  = (p, body) => api(p, { method: 'PUT',  body: JSON.stringify(body) });
const del  = (p)       => api(p, { method: 'DELETE' });

// ─── Toast ─────────────────────────────────────────────────────────────────
let toastTimer;
function toast(msg, dur = 2200) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), dur);
}

// ─── Haptic ────────────────────────────────────────────────────────────────
function haptic(type = 'light') {
  tg?.HapticFeedback?.impactOccurred(type);
}

// ─── Spinner ───────────────────────────────────────────────────────────────
function spinner() {
  return '<div class="spinner-wrap"><div class="spinner"></div></div>';
}

// ─── Navigation ───────────────────────────────────────────────────────────
function navigate(tab) {
  haptic('light');
  state.currentTab = tab;
  document.querySelectorAll('.nav-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  const titles = {
    dashboard: 'Dashboard', transactions: 'Transactions',
    add: 'New Record',      stats: 'Statistics',
    tasks: 'Tasks',         life: 'Life',        settings: 'Settings',
  };
  document.getElementById('screen-title').textContent = titles[tab] || tab;
  renderTab(tab);
}

async function renderTab(tab) {
  const content = document.getElementById('content');
  content.innerHTML = spinner();
  Object.values(state.charts).forEach(c => c?.destroy());
  state.charts = {};
  switch (tab) {
    case 'dashboard':    await renderDashboard(content);    break;
    case 'transactions': await renderTransactions(content); break;
    case 'add':          renderAdd(content);                break;
    case 'stats':        await renderStats(content);        break;
    case 'tasks':        await renderTasks(content);        break;
    case 'life':         await renderLife(content);         break;
    case 'settings':     await renderSettings(content);     break;
    default: content.innerHTML = '<div class="empty"><p>Coming soon</p></div>';
  }
}

// ─── Helpers ───────────────────────────────────────────────────────────────
function currSymbol(code) {
  return { USD:'$', EUR:'€', GBP:'£', RUB:'₽', CAD:'C$', AUD:'A$', UAH:'₴', PLN:'zł' }[code] || (code + ' ');
}
function fmtMoney(n, currency) {
  const sym = currency ? currSymbol(currency) : '';
  return sym + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function catIcon(catName) {
  const map = { Food:'🍔',Grocery:'🛒',Transport:'🚗',Fuel:'⛽',Entertainment:'🎬',Health:'💊',
    Shopping:'🛍',Rent:'🏠',Utilities:'💡',Income:'💵',Salary:'💵',Business:'💼',Other:'📦' };
  for (const [k, v] of Object.entries(map))
    if (catName && catName.toLowerCase().includes(k.toLowerCase())) return v;
  return state.categories.find(c => c.name === catName)?.icon || '📦';
}

// ─── DASHBOARD ─────────────────────────────────────────────────────────────
async function renderDashboard(content) {
  try {
    const [profile, stats, budgets, txData] = await Promise.all([
      get('/me'), get('/stats/month'), get('/budgets'), get('/transactions?per_page=5'),
    ]);
    state.user = profile;
    if (!state.categories.length) state.categories = await get('/categories');

    document.getElementById('user-avatar').textContent = profile.name[0].toUpperCase();
    const cur = profile.currency, sym = currSymbol(cur);
    const balSign = stats.balance >= 0 ? '+' : '';
    const balColor = stats.balance >= 0 ? 'rgba(255,255,255,0.9)' : '#ffcdd2';

    let html = `
      <div class="balance-card">
        <div class="label">Balance this month</div>
        <div>
          <span class="amount" style="color:${balColor}">${balSign}${fmtMoney(stats.balance)}</span>
          <span class="currency">${cur}</span>
        </div>
        <div class="balance-row">
          <div class="balance-col"><div class="b-label">↑ Income</div>
            <div class="b-val">${sym}${Number(stats.total_income).toLocaleString('en-US',{maximumFractionDigits:0})}</div></div>
          <div class="balance-col"><div class="b-label">↓ Expense</div>
            <div class="b-val">${sym}${Number(stats.total_expense).toLocaleString('en-US',{maximumFractionDigits:0})}</div></div>
        </div>
      </div>
      <div class="period-tabs" id="dash-period-tabs">
        ${['week','month','year'].map(p =>
          `<div class="period-tab ${p==='month'?'active':''}" onclick="dashChangePeriod('${p}')">${p.charAt(0).toUpperCase()+p.slice(1)}</div>`
        ).join('')}
      </div>`;

    if (stats.expense_categories.length > 0) {
      html += `<div class="card">
        <div style="font-size:13px;font-weight:600;color:var(--hint);margin-bottom:8px">EXPENSES BY CATEGORY</div>
        <div class="chart-wrap"><canvas id="donut-chart"></canvas></div>
        <div class="cat-legend" id="cat-legend"></div>
      </div>`;
    }

    const activeBudgets = budgets.filter(b => b.is_active).slice(0, 4);
    if (activeBudgets.length > 0) {
      html += `<div class="section-title">BUDGETS</div><div class="card" style="padding:0">
        ${activeBudgets.map(b => {
          const pct = Math.min(b.percent, 100), over = b.percent >= 100, warn = b.percent >= b.alert_at * 100;
          const barColor = over ? 'var(--destructive)' : warn ? '#f59e0b' : 'var(--btn)';
          return `<div class="progress-item">
            <div class="progress-info">
              <div class="progress-label">${b.category_icon||'💼'} ${b.category_name||'Overall'}</div>
              <div class="progress-sub">${fmtMoney(b.spent,cur)} / ${fmtMoney(b.amount,cur)} · ${b.period}</div>
            </div>
            <div class="progress-bar-wrap"><div class="progress-bar" style="width:${pct}%;background:${barColor}"></div></div>
            <div class="progress-pct" style="color:${over?'var(--destructive)':warn?'#f59e0b':'var(--hint)'}">${Math.round(b.percent)}%</div>
          </div>`;
        }).join('')}
      </div>`;
    }

    html += `<div class="section-title" style="display:flex;justify-content:space-between;align-items:center;padding-right:16px">
        RECENT <span style="color:var(--btn);font-size:13px;cursor:pointer" onclick="navigate('transactions')">See all →</span></div>
      <div class="tx-list">
        ${txData.items.length === 0
          ? '<div class="empty"><p>No transactions yet</p></div>'
          : txData.items.map(tx => txRow(tx, cur)).join('')}
      </div><div style="height:16px"></div>`;

    content.innerHTML = html;

    if (stats.expense_categories.length > 0) {
      const COLORS = ['#2481cc','#f59e0b','#2dbe6c','#e53935','#9c27b0','#00bcd4','#ff5722','#607d8b'];
      const cats = stats.expense_categories.slice(0, 8);
      const ctx = document.getElementById('donut-chart')?.getContext('2d');
      if (ctx) {
        state.charts.donut = new Chart(ctx, {
          type: 'doughnut',
          data: { labels: cats.map(c => c.name), datasets: [{
            data: cats.map(c => c.total), backgroundColor: COLORS, borderWidth: 2,
            borderColor: getComputedStyle(document.body).getPropertyValue('--bg') || '#fff',
          }]},
          options: { cutout: '68%', plugins: { legend: { display: false }, tooltip: {
            callbacks: { label: ctx => ` ${fmtMoney(ctx.parsed, cur)} (${cats[ctx.dataIndex].percent.toFixed(1)}%)` }
          }}},
        });
        document.getElementById('cat-legend').innerHTML = cats.map((c, i) =>
          `<div class="cat-legend-item">
            <div class="cat-dot" style="background:${COLORS[i]}"></div>
            <div class="cat-legend-name">${c.icon||'📦'} ${esc(c.name)}</div>
            <div class="cat-legend-val">${fmtMoney(c.total, cur)}</div>
            <div class="cat-legend-pct">${c.percent.toFixed(1)}%</div>
          </div>`
        ).join('');
      }
    }
  } catch (e) {
    content.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div><p>${esc(e.message)}</p></div>`;
  }
}

async function dashChangePeriod(period) {
  document.querySelectorAll('#dash-period-tabs .period-tab').forEach(t =>
    t.classList.toggle('active', t.textContent.toLowerCase() === period)
  );
  try {
    const stats = await get(`/stats/${period}`);
    const cur = state.user?.currency || 'USD';
    const amountEl = document.querySelector('.balance-card .amount');
    if (amountEl) amountEl.textContent = (stats.balance >= 0 ? '+' : '') + fmtMoney(stats.balance);
    const cols = document.querySelectorAll('.balance-col .b-val');
    if (cols[0]) cols[0].textContent = currSymbol(cur) + Number(stats.total_income).toLocaleString('en-US',{maximumFractionDigits:0});
    if (cols[1]) cols[1].textContent = currSymbol(cur) + Number(stats.total_expense).toLocaleString('en-US',{maximumFractionDigits:0});
  } catch (e) { toast(e.message); }
}

// ─── TX ROW ────────────────────────────────────────────────────────────────
function txRow(tx, currency) {
  const isExp = tx.type === 'expense';
  return `<div class="tx-item" onclick="showTxDetail('${tx.id}')">
    <div class="tx-icon ${tx.type}">${catIcon(tx.category)}</div>
    <div class="tx-body">
      <div class="tx-name">${esc(tx.merchant || tx.category)}</div>
      <div class="tx-sub">${esc(tx.category)} · ${fmtDate(tx.date)}</div>
    </div>
    <div class="tx-amount ${tx.type}">${isExp?'-':'+'} ${fmtMoney(tx.amount, currency)}</div>
  </div>`;
}

// ─── TRANSACTIONS ──────────────────────────────────────────────────────────
async function renderTransactions(content) {
  state.txPage = 1;
  const cats = state.categories;
  content.innerHTML = `
    <div class="search-bar">
      <span>🔍</span>
      <input type="text" placeholder="Search…" id="tx-search" value="${esc(state.txFilter.search)}"
        oninput="state.txFilter.search=this.value;debounceLoadTx()">
    </div>
    <div class="filter-row" id="tx-filters">
      <div class="chip ${!state.txFilter.type?'active':''}" onclick="setTxFilter('type',null,this)">All</div>
      <div class="chip ${state.txFilter.type==='expense'?'active':''}" onclick="setTxFilter('type','expense',this)">Expenses</div>
      <div class="chip ${state.txFilter.type==='income'?'active':''}"  onclick="setTxFilter('type','income',this)">Income</div>
      ${cats.slice(0,6).map(c =>
        `<div class="chip ${state.txFilter.category===c.id?'active':''}" onclick="setTxCat('${c.id}',this)">${c.icon||'📦'} ${esc(c.name)}</div>`
      ).join('')}
    </div>
    <div id="tx-list-container">${spinner()}</div>`;
  await loadTransactions();
}

function setTxFilter(key, val, el) {
  haptic('light');
  if (key === 'type') {
    state.txFilter.type = val;
    document.querySelectorAll('#tx-filters .chip').forEach(c => {
      if (c.textContent.trim() === 'All')      c.classList.toggle('active', val === null);
      if (c.textContent.trim() === 'Expenses') c.classList.toggle('active', val === 'expense');
      if (c.textContent.trim() === 'Income')   c.classList.toggle('active', val === 'income');
    });
  }
  state.txPage = 1;
  loadTransactions();
}
function setTxCat(id, el) {
  haptic('light');
  state.txFilter.category = state.txFilter.category === id ? null : id;
  document.querySelectorAll('#tx-filters .chip').forEach(c => {
    if (c.onclick?.toString().includes(id)) c.classList.toggle('active', state.txFilter.category === id);
  });
  state.txPage = 1;
  loadTransactions();
}

let txDebounce;
function debounceLoadTx() { clearTimeout(txDebounce); txDebounce = setTimeout(loadTransactions, 350); }

async function loadTransactions() {
  const container = document.getElementById('tx-list-container');
  if (!container) return;
  container.innerHTML = spinner();
  const f = state.txFilter;
  const params = new URLSearchParams({ page: state.txPage, per_page: 20 });
  if (f.type)     params.set('type', f.type);
  if (f.category) params.set('category_id', f.category);
  if (f.search)   params.set('search', f.search);
  try {
    const data = await get(`/transactions?${params}`);
    const cur = state.user?.currency || 'USD';
    if (data.items.length === 0) {
      container.innerHTML = `<div class="empty"><div class="empty-icon">💸</div><p>No transactions</p><small>Try adjusting filters</small></div>`;
      return;
    }
    container.innerHTML = `
      <div class="tx-list">${data.items.map(tx => txRow(tx, cur)).join('')}</div>
      ${data.total > state.txPage * 20
        ? `<div class="btn-wrap"><button class="btn btn-ghost" onclick="loadMoreTx()">Load more (${data.total - state.txPage*20} left)</button></div>` : ''}
      <div style="height:16px"></div>`;
  } catch (e) {
    container.innerHTML = `<div class="empty"><p>${esc(e.message)}</p></div>`;
  }
}

async function loadMoreTx() { state.txPage++; await loadTransactions(); }

async function showTxDetail(id) {
  haptic('light');
  openModal(spinner());
  try {
    const tx = await get(`/transactions/${id}`);
    const cur = state.user?.currency || 'USD';
    const isExp = tx.type === 'expense';
    setModalContent(`
      <div class="modal-title">Transaction Details</div>
      <div style="padding:0 16px">
        <div style="text-align:center;padding:16px 0 20px">
          <div style="font-size:48px">${catIcon(tx.category)}</div>
          <div style="font-size:28px;font-weight:700;color:${isExp?'var(--destructive)':'#2dbe6c'};margin-top:8px">
            ${isExp?'-':'+'} ${fmtMoney(tx.amount, cur)}</div>
          <div style="color:var(--hint);font-size:14px;margin-top:4px">${esc(tx.category)}</div>
        </div>
        <div class="card" style="margin:0 0 12px">
          ${detailRow('Merchant', tx.merchant || '—')}
          ${detailRow('Date', fmtDate(tx.date))}
          ${detailRow('Type', tx.type)} ${detailRow('Scope', tx.scope)}
          ${tx.description ? detailRow('Note', tx.description) : ''}
        </div>
        <div style="display:flex;gap:8px;margin-bottom:16px">
          <button class="btn btn-ghost" style="flex:1" onclick="editTxModal('${tx.id}')">✏️ Edit</button>
          <button class="btn btn-danger" style="flex:1" onclick="deleteTx('${tx.id}')">🗑 Delete</button>
        </div>
      </div>`);
  } catch (e) { setModalContent(`<div class="empty"><p>${esc(e.message)}</p></div>`); }
}

function detailRow(label, val) {
  return `<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--section-sep)">
    <span style="color:var(--hint);font-size:14px">${esc(label)}</span>
    <span style="font-size:14px;font-weight:500">${esc(String(val))}</span>
  </div>`;
}

async function deleteTx(id) {
  haptic('medium');
  if (!confirm('Delete this transaction?')) return;
  try {
    await del(`/transactions/${id}`);
    closeModal();
    toast('✅ Deleted');
    if (state.currentTab === 'transactions') loadTransactions();
    else renderTab('dashboard');
  } catch (e) { toast('❌ ' + e.message); }
}

async function editTxModal(id) {
  openModal(spinner());
  try {
    const tx = await get(`/transactions/${id}`);
    const cats = state.categories;
    setModalContent(`
      <div class="modal-title">Edit Transaction</div>
      <div class="form-group"><div class="form-label">Amount</div>
        <input class="form-input" id="edit-amount" type="number" step="0.01" value="${tx.amount}" min="0.01"></div>
      <div class="form-group"><div class="form-label">Category</div>
        <select class="form-input" id="edit-cat">
          ${cats.map(c=>`<option value="${c.id}" ${c.id===tx.category_id?'selected':''}>${c.icon||''} ${esc(c.name)}</option>`).join('')}
        </select></div>
      <div class="form-group"><div class="form-label">Merchant</div>
        <input class="form-input" id="edit-merchant" type="text" value="${esc(tx.merchant||'')}"></div>
      <div class="form-group"><div class="form-label">Date</div>
        <input class="form-input" id="edit-date" type="date" value="${tx.date}"></div>
      <div class="form-group"><div class="form-label">Note</div>
        <input class="form-input" id="edit-desc" type="text" value="${esc(tx.description||'')}"></div>
      <div class="btn-wrap" style="padding-bottom:16px">
        <button class="btn btn-primary" onclick="submitEditTx('${id}')">Save changes</button></div>`);
  } catch (e) { setModalContent(`<div class="empty"><p>${esc(e.message)}</p></div>`); }
}

async function submitEditTx(id) {
  haptic('medium');
  try {
    await put(`/transactions/${id}`, {
      amount:      parseFloat(document.getElementById('edit-amount').value),
      category_id: document.getElementById('edit-cat').value,
      merchant:    document.getElementById('edit-merchant').value || null,
      date:        document.getElementById('edit-date').value,
      description: document.getElementById('edit-desc').value || null,
    });
    closeModal();
    toast('✅ Updated');
    if (state.currentTab === 'transactions') loadTransactions();
    else renderTab('dashboard');
  } catch (e) { toast('❌ ' + e.message); }
}

// ─── ADD ──────────────────────────────────────────────────────────────────
let addType = 'expense';

function renderAdd(content) {
  const cats = state.categories;
  const today = new Date().toISOString().split('T')[0];
  content.innerHTML = `
    <div style="padding:12px 0 0">
      <div class="form-group">
        <div class="type-toggle">
          <div class="type-btn active expense" onclick="setAddType('expense')">Expense</div>
          <div class="type-btn income"          onclick="setAddType('income')">Income</div>
        </div>
      </div>
      <div class="amount-input-wrap">
        <span class="currency-symbol">${currSymbol(state.user?.currency||'USD')}</span>
        <input class="amount-input-large" id="add-amount" type="number" step="0.01" min="0.01"
          placeholder="0.00" inputmode="decimal" autofocus>
      </div>
      <div class="form-group">
        <div class="form-label">Category</div>
        <div class="cat-grid" id="add-cat-grid">
          ${cats.slice(0,12).map((c,i) =>
            `<div class="cat-chip ${i===0?'selected':''}" data-id="${c.id}" onclick="selectCat(this)">
              <div class="cat-emoji">${c.icon||'📦'}</div>
              <div class="cat-label">${esc(c.name)}</div>
            </div>`
          ).join('')}
        </div>
      </div>
      <div class="form-group"><div class="form-label">Merchant / Source</div>
        <input class="form-input" id="add-merchant" type="text" placeholder="e.g. Walmart, Salary"></div>
      <div class="form-group"><div class="form-label">Date</div>
        <input class="form-input" id="add-date" type="date" value="${today}"></div>
      <div class="form-group"><div class="form-label">Note (optional)</div>
        <input class="form-input" id="add-desc" type="text" placeholder="Description"></div>
      <div class="btn-wrap" style="padding-bottom:16px">
        <button class="btn btn-primary" onclick="submitAdd()">💾 Save</button>
      </div>
    </div>`;
}

function setAddType(type) {
  addType = type;
  haptic('light');
  document.querySelectorAll('.type-btn').forEach(b =>
    b.classList.toggle('active', b.textContent.toLowerCase() === type)
  );
}

function selectCat(el) {
  haptic('selection');
  document.querySelectorAll('#add-cat-grid .cat-chip').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
}

async function submitAdd() {
  haptic('medium');
  const amount   = parseFloat(document.getElementById('add-amount')?.value);
  const catEl    = document.querySelector('#add-cat-grid .cat-chip.selected');
  const merchant = document.getElementById('add-merchant')?.value.trim() || null;
  const txDate   = document.getElementById('add-date')?.value;
  const desc     = document.getElementById('add-desc')?.value.trim() || null;
  if (!amount || amount <= 0) { toast('⚠️ Enter amount'); return; }
  if (!catEl)                  { toast('⚠️ Pick a category'); return; }
  const btn = document.querySelector('#content .btn-primary');
  if (btn) { btn.textContent = 'Saving…'; btn.disabled = true; }
  try {
    await post('/transactions', { amount, type: addType, category_id: catEl.dataset.id, merchant, date: txDate, description: desc });
    toast('✅ Saved!');
    navigate('dashboard');
  } catch (e) {
    toast('❌ ' + e.message);
    if (btn) { btn.textContent = '💾 Save'; btn.disabled = false; }
  }
}

// ─── STATS ─────────────────────────────────────────────────────────────────
async function renderStats(content) {
  const period = state.statsperiod || 'month';
  content.innerHTML = `
    <div class="period-tabs">
      ${['week','month','year'].map(p =>
        `<div class="period-tab ${p===period?'active':''}" onclick="statsChangePeriod('${p}')">${p.charAt(0).toUpperCase()+p.slice(1)}</div>`
      ).join('')}
    </div>
    <div id="stats-body">${spinner()}</div>`;
  await loadStats(period);
}

async function statsChangePeriod(period) {
  haptic('light');
  state.statsperiod = period;
  document.querySelectorAll('.period-tab').forEach(t =>
    t.classList.toggle('active', t.textContent.toLowerCase() === period)
  );
  const body = document.getElementById('stats-body');
  if (body) { body.innerHTML = spinner(); await loadStats(period); }
}

async function loadStats(period) {
  const body = document.getElementById('stats-body');
  if (!body) return;
  try {
    const [stats, trend] = await Promise.all([get(`/stats/${period}`), get('/stats/trend/monthly?months=6')]);
    const cur = state.user?.currency || 'USD', sym = currSymbol(cur);
    const COLORS = ['#2481cc','#f59e0b','#2dbe6c','#e53935','#9c27b0','#00bcd4','#ff5722','#607d8b'];

    let html = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:12px 12px 0">
        <div class="card" style="margin:0;text-align:center">
          <div style="font-size:12px;color:var(--hint)">Total Expense</div>
          <div style="font-size:20px;font-weight:700;color:var(--destructive);margin-top:4px">${sym}${Number(stats.total_expense).toLocaleString('en-US',{maximumFractionDigits:0})}</div>
        </div>
        <div class="card" style="margin:0;text-align:center">
          <div style="font-size:12px;color:var(--hint)">Total Income</div>
          <div style="font-size:20px;font-weight:700;color:#2dbe6c;margin-top:4px">${sym}${Number(stats.total_income).toLocaleString('en-US',{maximumFractionDigits:0})}</div>
        </div>
      </div>`;

    if (stats.expense_categories.length > 0) {
      html += `<div class="section-title">SPENDING BREAKDOWN</div>
        <div class="card">
          <div class="chart-wrap"><canvas id="stats-donut"></canvas></div>
          <div class="cat-legend" id="stats-legend"></div>
        </div>`;
    }
    html += `<div class="section-title">6-MONTH TREND</div>
      <div class="card"><div class="chart-wrap"><canvas id="stats-bar"></canvas></div></div>
      <div style="height:16px"></div>`;

    body.innerHTML = html;
    Object.values(state.charts).forEach(c => c?.destroy());
    state.charts = {};

    if (stats.expense_categories.length > 0) {
      const cats = stats.expense_categories.slice(0, 8);
      const ctx1 = document.getElementById('stats-donut')?.getContext('2d');
      if (ctx1) {
        state.charts.statsDonut = new Chart(ctx1, {
          type: 'doughnut',
          data: { labels: cats.map(c=>c.name), datasets:[{ data:cats.map(c=>c.total), backgroundColor:COLORS, borderWidth:2 }]},
          options: { cutout:'65%', plugins:{ legend:{ display:false } } },
        });
        document.getElementById('stats-legend').innerHTML = cats.map((c,i) =>
          `<div class="cat-legend-item">
            <div class="cat-dot" style="background:${COLORS[i]}"></div>
            <div class="cat-legend-name">${c.icon||'📦'} ${esc(c.name)}</div>
            <div class="cat-legend-val">${sym}${Number(c.total).toLocaleString('en-US',{maximumFractionDigits:0})}</div>
            <div class="cat-legend-pct">${c.percent.toFixed(1)}%</div>
          </div>`
        ).join('');
      }
    }

    const ctx2 = document.getElementById('stats-bar')?.getContext('2d');
    if (ctx2 && trend.length > 0) {
      state.charts.statsBar = new Chart(ctx2, {
        type: 'bar',
        data: {
          labels: trend.map(t => t.month),
          datasets: [
            { label:'Expense', data:trend.map(t=>t.expense), backgroundColor:'rgba(229,57,53,0.7)' },
            { label:'Income',  data:trend.map(t=>t.income),  backgroundColor:'rgba(45,190,108,0.7)' },
          ],
        },
        options: {
          plugins: { legend:{ position:'bottom', labels:{ boxWidth:12 } } },
          scales: {
            x: { grid:{ display:false } },
            y: { ticks:{ callback: v => sym + Number(v).toLocaleString('en-US',{maximumFractionDigits:0}) } },
          },
        },
      });
    }
  } catch (e) { body.innerHTML = `<div class="empty"><p>${esc(e.message)}</p></div>`; }
}

// ─── TASKS ─────────────────────────────────────────────────────────────────
async function renderTasks(content) {
  content.innerHTML = `
    <div class="filter-row">
      <div class="chip active" onclick="filterTasks(null,this)">All</div>
      <div class="chip" onclick="filterTasks('pending',this)">Pending</div>
      <div class="chip" onclick="filterTasks('in_progress',this)">In Progress</div>
      <div class="chip" onclick="filterTasks('done',this)">Done</div>
    </div>
    <div id="task-list">${spinner()}</div>
    <div class="btn-wrap">
      <button class="btn btn-primary" onclick="addTaskModal()">+ New Task</button>
    </div><div style="height:16px"></div>`;
  await loadTaskList(null);
}

window.filterTasks = async (status, el) => {
  haptic('light');
  document.querySelectorAll('.filter-row .chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  await loadTaskList(status);
};

async function loadTaskList(status) {
  const taskList = document.getElementById('task-list');
  if (!taskList) return;
  taskList.innerHTML = spinner();
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  try {
    const tasks = await get('/tasks?' + params);
    if (tasks.length === 0) {
      taskList.innerHTML = `<div class="empty"><div class="empty-icon">✅</div><p>All done!</p><small>Add a new task below</small></div>`;
      return;
    }
    taskList.innerHTML = `<div class="tx-list">
      ${tasks.map(t => `
        <div class="task-item">
          <div class="task-check ${t.status==='done'?'done':''}" onclick="toggleTask('${t.id}','${t.status}')">
            ${t.status==='done'?'✓':''}
          </div>
          <div class="task-body" onclick="editTaskModal('${t.id}')">
            <div class="task-title ${t.status==='done'?'done':''}">${esc(t.title)}</div>
            ${t.due_at ? `<div class="task-sub">📅 ${fmtDate(t.due_at)}</div>` : ''}
          </div>
          <div class="priority-badge ${t.priority}">${t.priority}</div>
        </div>`).join('')}
    </div>`;
  } catch (e) { taskList.innerHTML = `<div class="empty"><p>${esc(e.message)}</p></div>`; }
}

async function toggleTask(id, currentStatus) {
  haptic('medium');
  const newStatus = currentStatus === 'done' ? 'pending' : 'done';
  try {
    await put(`/tasks/${id}`, { status: newStatus });
    toast(newStatus === 'done' ? '✅ Done!' : '↩️ Reopened');
    await loadTaskList(null);
  } catch (e) { toast('❌ ' + e.message); }
}

function addTaskModal() {
  haptic('light');
  openModal(`
    <div class="modal-title">New Task</div>
    <div class="form-group"><div class="form-label">Title</div>
      <input class="form-input" id="task-title" type="text" placeholder="What needs to be done?"></div>
    <div class="form-group"><div class="form-label">Priority</div>
      <select class="form-input" id="task-priority">
        <option value="low">🟢 Low</option><option value="medium" selected>🟡 Medium</option>
        <option value="high">🔴 High</option><option value="urgent">🚨 Urgent</option>
      </select></div>
    <div class="form-group"><div class="form-label">Due date (optional)</div>
      <input class="form-input" id="task-due" type="date"></div>
    <div class="form-group"><div class="form-label">Description (optional)</div>
      <input class="form-input" id="task-desc" type="text" placeholder="Details…"></div>
    <div class="btn-wrap" style="padding-bottom:16px">
      <button class="btn btn-primary" onclick="submitAddTask()">Add Task</button></div>`);
  setTimeout(() => document.getElementById('task-title')?.focus(), 300);
}

async function submitAddTask() {
  haptic('medium');
  const title = document.getElementById('task-title')?.value.trim();
  if (!title) { toast('⚠️ Enter title'); return; }
  const dueRaw = document.getElementById('task-due')?.value;
  try {
    await post('/tasks', {
      title, priority: document.getElementById('task-priority')?.value || 'medium',
      due_at: dueRaw ? dueRaw + 'T00:00:00' : null,
      description: document.getElementById('task-desc')?.value.trim() || null,
    });
    closeModal();
    toast('✅ Task added');
    await loadTaskList(null);
  } catch (e) { toast('❌ ' + e.message); }
}

async function editTaskModal(id) {
  haptic('light');
  openModal(spinner());
  try {
    const tasks = await get('/tasks');
    const t = tasks.find(x => x.id === id);
    if (!t) { setModalContent(`<div class="empty"><p>Not found</p></div>`); return; }
    setModalContent(`
      <div class="modal-title">Edit Task</div>
      <div class="form-group"><div class="form-label">Title</div>
        <input class="form-input" id="etask-title" type="text" value="${esc(t.title)}"></div>
      <div class="form-group"><div class="form-label">Status</div>
        <select class="form-input" id="etask-status">
          <option value="pending"     ${t.status==='pending'?'selected':''}>Pending</option>
          <option value="in_progress" ${t.status==='in_progress'?'selected':''}>In Progress</option>
          <option value="done"        ${t.status==='done'?'selected':''}>Done</option>
          <option value="cancelled"   ${t.status==='cancelled'?'selected':''}>Cancelled</option>
        </select></div>
      <div class="form-group"><div class="form-label">Priority</div>
        <select class="form-input" id="etask-priority">
          <option value="low"    ${t.priority==='low'?'selected':''}>🟢 Low</option>
          <option value="medium" ${t.priority==='medium'?'selected':''}>🟡 Medium</option>
          <option value="high"   ${t.priority==='high'?'selected':''}>🔴 High</option>
          <option value="urgent" ${t.priority==='urgent'?'selected':''}>🚨 Urgent</option>
        </select></div>
      <div style="display:flex;gap:8px;padding:0 12px 16px;margin-top:8px">
        <button class="btn btn-primary" style="flex:2" onclick="submitEditTask('${id}')">Save</button>
        <button class="btn btn-danger"  style="flex:1" onclick="deleteTask('${id}')">Delete</button>
      </div>`);
  } catch (e) { setModalContent(`<div class="empty"><p>${esc(e.message)}</p></div>`); }
}

async function submitEditTask(id) {
  haptic('medium');
  try {
    await put(`/tasks/${id}`, {
      title:    document.getElementById('etask-title')?.value.trim(),
      status:   document.getElementById('etask-status')?.value,
      priority: document.getElementById('etask-priority')?.value,
    });
    closeModal();
    toast('✅ Saved');
    await loadTaskList(null);
  } catch (e) { toast('❌ ' + e.message); }
}

async function deleteTask(id) {
  haptic('medium');
  if (!confirm('Delete task?')) return;
  try {
    await del(`/tasks/${id}`);
    closeModal(); toast('🗑 Deleted');
    await loadTaskList(null);
  } catch (e) { toast('❌ ' + e.message); }
}

// ─── LIFE ──────────────────────────────────────────────────────────────────
async function renderLife(content) {
  const today = new Date().toISOString().split('T')[0];
  try {
    const events = await get(`/life-events?date_from=${today}&date_to=${today}&limit=50`);
    content.innerHTML = `
      <div class="section-title">QUICK LOG</div>
      <div style="padding:0 12px">
        <div class="life-quick-grid">
          <div class="life-btn" onclick="logMood()"><span class="life-icon">😊</span><span class="life-label">Mood</span></div>
          <div class="life-btn" onclick="logFood()"><span class="life-icon">🍽</span><span class="life-label">Food</span></div>
          <div class="life-btn" onclick="logDrink()"><span class="life-icon">💧</span><span class="life-label">Drink</span></div>
          <div class="life-btn" onclick="logNote()"><span class="life-icon">📝</span><span class="life-label">Note</span></div>
          <div class="life-btn" onclick="logReflection()"><span class="life-icon">🌙</span><span class="life-label">Reflect</span></div>
          <div class="life-btn" onclick="navigate('tasks')"><span class="life-icon">✅</span><span class="life-label">Tasks</span></div>
        </div>
      </div>
      <div class="section-title">TODAY — ${new Date().toLocaleDateString('en-US',{month:'long',day:'numeric'})}</div>
      <div class="tx-list">
        ${events.length === 0
          ? '<div class="empty"><p>Nothing logged yet today</p></div>'
          : events.map(e => `
              <div class="event-item">
                <div class="event-icon">${lifeIcon(e.type)}</div>
                <div class="event-body">
                  <div class="event-text">${esc(e.text || lifeEventSummary(e))}</div>
                  <div class="event-meta">${e.type} · ${new Date(e.created_at).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'})}</div>
                </div>
              </div>`).join('')}
      </div><div style="height:16px"></div>`;
  } catch (e) { content.innerHTML = `<div class="empty"><p>${esc(e.message)}</p></div>`; }
}

function lifeIcon(t) { return {note:'📝',food:'🍽',drink:'💧',mood:'😊',task:'✅',reflection:'🌙'}[t]||'💬'; }
function lifeEventSummary(e) {
  if (e.type==='mood'&&e.data?.score) return `Mood: ${e.data.score}/10`;
  if (e.type==='food'&&e.data?.items) return e.data.items.join(', ');
  if (e.type==='drink'&&e.data?.drink) return e.data.drink;
  return e.type;
}

let selectedMoodScore = null;
function logMood() {
  haptic('light');
  openModal(`
    <div class="modal-title">How are you feeling?</div>
    <div class="mood-grid">
      ${[['😢','Bad',1],['😕','Meh',4],['😐','OK',6],['🙂','Good',8],['😄','Great',10]].map(([em,lb,sc]) =>
        `<div class="mood-btn" onclick="selectMood(${sc},this)">
          <span class="mood-emoji">${em}</span><span class="mood-label">${lb}</span>
        </div>`).join('')}
    </div>
    <div class="form-group" style="margin-top:12px"><div class="form-label">Note (optional)</div>
      <input class="form-input" id="mood-note" type="text" placeholder="What's on your mind?"></div>
    <div id="mood-sel" style="text-align:center;padding:8px;color:var(--hint);font-size:13px">Select a mood above</div>
    <div class="btn-wrap" style="padding-bottom:16px">
      <button class="btn btn-primary" id="mood-save" disabled onclick="doSaveMood()">Save</button></div>`);
}
function selectMood(score, el) {
  haptic('selection'); selectedMoodScore = score;
  document.querySelectorAll('.mood-btn').forEach(b => b.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('mood-sel').textContent = `Score: ${score}/10`;
  document.getElementById('mood-save').disabled = false;
}
async function doSaveMood() {
  if (!selectedMoodScore) return;
  haptic('medium');
  try {
    await post('/life-events', { type:'mood', text: document.getElementById('mood-note')?.value.trim()||null, data:{score:selectedMoodScore} });
    closeModal(); toast('😊 Mood logged'); selectedMoodScore = null;
    if (state.currentTab==='life') renderLife(document.getElementById('content'));
  } catch (e) { toast('❌ '+e.message); }
}

function logFood() {
  haptic('light');
  openModal(`
    <div class="modal-title">Log Food 🍽</div>
    <div class="form-group"><div class="form-label">What did you eat?</div>
      <input class="form-input" id="food-text" type="text" placeholder="e.g. Grilled chicken, salad, rice"></div>
    <div class="form-group"><div class="form-label">Meal type</div>
      <select class="form-input" id="food-meal">
        <option>Breakfast</option><option>Lunch</option><option>Dinner</option><option>Snack</option>
      </select></div>
    <div class="btn-wrap" style="padding-bottom:16px">
      <button class="btn btn-primary" onclick="submitLifeEvent('food')">Log</button></div>`);
  setTimeout(() => document.getElementById('food-text')?.focus(), 300);
}

function logDrink() {
  haptic('light');
  openModal(`
    <div class="modal-title">Log Drink 💧</div>
    <div class="form-group">
      <div style="display:flex;flex-wrap:wrap;gap:8px;padding:4px 0 8px">
        ${['💧 Water','☕ Coffee','🍵 Tea','🧃 Juice','🥛 Milk','🥤 Soda'].map(d =>
          `<div class="chip" onclick="this.classList.toggle('active');document.getElementById('drink-text').value=this.textContent.trim()">${d}</div>`
        ).join('')}
      </div>
      <input class="form-input" id="drink-text" type="text" placeholder="Or type here…"></div>
    <div class="btn-wrap" style="padding-bottom:16px">
      <button class="btn btn-primary" onclick="submitLifeEvent('drink')">Log</button></div>`);
}

function logNote() {
  haptic('light');
  openModal(`
    <div class="modal-title">Quick Note 📝</div>
    <div class="form-group">
      <textarea class="form-input" id="note-text" rows="4" placeholder="Write anything…" style="resize:none;padding-top:12px"></textarea></div>
    <div class="btn-wrap" style="padding-bottom:16px">
      <button class="btn btn-primary" onclick="submitLifeEvent('note')">Save Note</button></div>`);
  setTimeout(() => document.getElementById('note-text')?.focus(), 300);
}

function logReflection() {
  haptic('light');
  openModal(`
    <div class="modal-title">Daily Reflection 🌙</div>
    <div class="form-group"><div class="form-label">What went well today?</div>
      <input class="form-input" id="ref-good" type="text" placeholder="Something positive…"></div>
    <div class="form-group"><div class="form-label">What could be better?</div>
      <input class="form-input" id="ref-improve" type="text" placeholder="Area to improve…"></div>
    <div class="form-group"><div class="form-label">Key takeaway</div>
      <input class="form-input" id="ref-takeaway" type="text" placeholder="Main lesson or thought…"></div>
    <div class="btn-wrap" style="padding-bottom:16px">
      <button class="btn btn-primary" onclick="submitReflection()">Save Reflection</button></div>`);
}

async function submitReflection() {
  haptic('medium');
  const good     = document.getElementById('ref-good')?.value.trim();
  const improve  = document.getElementById('ref-improve')?.value.trim();
  const takeaway = document.getElementById('ref-takeaway')?.value.trim();
  const text = [good&&`✅ ${good}`, improve&&`🔧 ${improve}`, takeaway&&`💡 ${takeaway}`].filter(Boolean).join('\n');
  if (!text) { toast('⚠️ Fill in at least one field'); return; }
  try {
    await post('/life-events', { type:'reflection', text, data:{good,improve,takeaway} });
    closeModal(); toast('🌙 Reflection saved');
    if (state.currentTab==='life') renderLife(document.getElementById('content'));
  } catch (e) { toast('❌ '+e.message); }
}

async function submitLifeEvent(type) {
  haptic('medium');
  let text = '', data = {};
  if (type==='food') {
    text = document.getElementById('food-text')?.value.trim();
    data = { items: text.split(',').map(s=>s.trim()).filter(Boolean), meal: document.getElementById('food-meal')?.value };
  } else if (type==='drink') {
    text = document.getElementById('drink-text')?.value.trim();
    data = { drink: text };
  } else if (type==='note') {
    text = document.getElementById('note-text')?.value.trim();
  }
  if (!text) { toast('⚠️ Enter something'); return; }
  try {
    await post('/life-events', { type, text, data });
    closeModal(); toast('✅ Logged');
    if (state.currentTab==='life') renderLife(document.getElementById('content'));
  } catch (e) { toast('❌ '+e.message); }
}

// ─── SETTINGS ──────────────────────────────────────────────────────────────
async function renderSettings(content) {
  try {
    const [profile, recurring] = await Promise.all([get('/me'), get('/recurring')]);
    state.user = profile;
    content.innerHTML = `
      <div class="card" style="display:flex;align-items:center;gap:14px">
        <div class="avatar" style="width:52px;height:52px;font-size:22px">${profile.name[0].toUpperCase()}</div>
        <div>
          <div style="font-size:17px;font-weight:600">${esc(profile.name)}</div>
          <div style="font-size:13px;color:var(--hint)">${profile.role} · ${esc(profile.family_name)}</div>
          <div style="font-size:12px;color:var(--hint);margin-top:2px">${esc(profile.business_type||'Personal')}</div>
        </div>
      </div>

      <div class="section-title">QUICK ACTIONS</div>
      <div class="card" style="padding:0">
        <div class="settings-row" onclick="navigate('stats')">
          <div class="row-left"><span class="row-icon">📊</span><span class="row-label">Statistics</span></div><span class="row-arrow">›</span></div>
        <div class="settings-row" onclick="navigate('life')">
          <div class="row-left"><span class="row-icon">🌿</span><span class="row-label">Life Tracking</span></div><span class="row-arrow">›</span></div>
        <div class="settings-row" onclick="openBudgetsModal()">
          <div class="row-left"><span class="row-icon">🎯</span><span class="row-label">Manage Budgets</span></div><span class="row-arrow">›</span></div>
      </div>

      <div class="section-title">PREFERENCES</div>
      <div class="card" style="padding:0">
        <div class="settings-row" onclick="changeLang()">
          <div class="row-left"><span class="row-icon">🌍</span><span class="row-label">Language</span></div>
          <span class="row-value">${profile.language.toUpperCase()}</span></div>
        <div class="settings-row" onclick="changeCurrency()">
          <div class="row-left"><span class="row-icon">💱</span><span class="row-label">Currency</span></div>
          <span class="row-value">${profile.currency}</span></div>
      </div>

      <div class="section-title">FAMILY</div>
      <div class="card" style="padding:0">
        <div class="settings-row" onclick="showInviteCode()">
          <div class="row-left"><span class="row-icon">🔗</span><span class="row-label">Invite Code</span></div>
          <span class="row-value" style="font-family:monospace;font-weight:600">${profile.invite_code}</span></div>
      </div>

      ${recurring.length > 0 ? `
        <div class="section-title">SUBSCRIPTIONS & RECURRING</div>
        <div class="card" style="padding:0">
          ${recurring.map(r => `
            <div class="rec-item">
              <div style="font-size:22px">${r.category_icon||'🔄'}</div>
              <div class="rec-body">
                <div class="rec-name">${esc(r.name)}</div>
                <div class="rec-sub">${r.frequency} · next: ${fmtDate(r.next_date)}</div>
              </div>
              <div>
                <div class="rec-amount">-${fmtMoney(r.amount)}</div>
                <button class="btn btn-sm btn-ghost" style="margin-top:4px" onclick="markRecurringPaid('${r.id}')">✓ Paid</button>
              </div>
            </div>`).join('')}
        </div>` : ''}

      <div class="section-title">DATA</div>
      <div class="card" style="padding:0">
        <div class="settings-row" onclick="exportCSV()">
          <div class="row-left"><span class="row-icon">📥</span><span class="row-label">Export to CSV</span></div>
          <span class="row-arrow">›</span></div>
      </div>
      <div style="height:16px"></div>`;
  } catch (e) { content.innerHTML = `<div class="empty"><p>${esc(e.message)}</p></div>`; }
}

async function openBudgetsModal() {
  haptic('light');
  openModal(spinner());
  try {
    const [budgets, cats] = await Promise.all([get('/budgets'), get('/categories')]);
    const cur = state.user?.currency || 'USD', sym = currSymbol(cur);
    setModalContent(`
      <div class="modal-title">Budgets</div>
      <div class="card" style="margin:0 0 12px;padding:0">
        ${budgets.length === 0
          ? '<div class="empty"><p>No budgets yet</p></div>'
          : budgets.map(b => {
              const pct = Math.min(b.percent, 100), over = b.percent >= 100;
              return `<div class="progress-item">
                <div class="progress-info">
                  <div class="progress-label">${b.category_icon||'💼'} ${b.category_name||'Overall'}</div>
                  <div class="progress-sub">${sym}${b.spent.toLocaleString()} / ${sym}${b.amount.toLocaleString()} · ${b.period}</div>
                </div>
                <div style="display:flex;align-items:center;gap:6px">
                  <div class="progress-bar-wrap"><div class="progress-bar ${over?'over':''}" style="width:${pct}%"></div></div>
                  <div class="progress-pct">${Math.round(b.percent)}%</div>
                  <button class="btn btn-sm btn-danger" onclick="deleteBudget('${b.id}')">✕</button>
                </div>
              </div>`;
            }).join('')}
      </div>
      <div class="section-title" style="padding-left:0">ADD BUDGET</div>
      <div class="form-group" style="padding:0 0 8px"><div class="form-label">Category (blank = overall)</div>
        <select class="form-input" id="new-bud-cat">
          <option value="">— Overall budget —</option>
          ${cats.map(c=>`<option value="${c.id}">${c.icon||''} ${esc(c.name)}</option>`).join('')}
        </select></div>
      <div style="display:flex;gap:8px;padding:0 0 8px">
        <div style="flex:1"><div class="form-label">Amount</div>
          <input class="form-input" id="new-bud-amount" type="number" placeholder="500" min="1"></div>
        <div style="flex:1"><div class="form-label">Period</div>
          <select class="form-input" id="new-bud-period">
            <option value="monthly">Monthly</option><option value="weekly">Weekly</option>
          </select></div>
      </div>
      <div style="padding:0 0 16px">
        <button class="btn btn-primary" onclick="addBudget()">Add Budget</button></div>`);
  } catch (e) { setModalContent(`<div class="empty"><p>${esc(e.message)}</p></div>`); }
}

async function addBudget() {
  haptic('medium');
  const catId  = document.getElementById('new-bud-cat')?.value || null;
  const amount = parseFloat(document.getElementById('new-bud-amount')?.value);
  const period = document.getElementById('new-bud-period')?.value || 'monthly';
  if (!amount || amount <= 0) { toast('⚠️ Enter amount'); return; }
  try {
    await post('/budgets', { category_id: catId||null, amount, period, scope:'family' });
    toast('✅ Budget added');
    await openBudgetsModal();
  } catch (e) { toast('❌ '+e.message); }
}

async function deleteBudget(id) {
  haptic('medium');
  if (!confirm('Remove budget?')) return;
  try {
    await del(`/budgets/${id}`);
    toast('🗑 Removed');
    await openBudgetsModal();
  } catch (e) { toast('❌ '+e.message); }
}

async function markRecurringPaid(id) {
  haptic('medium');
  try {
    const res = await put(`/recurring/${id}/mark-paid`, {});
    toast(`✅ Paid! Next: ${fmtDate(res.next_date)}`);
    await renderSettings(document.getElementById('content'));
  } catch (e) { toast('❌ '+e.message); }
}

function changeLang() {
  openModal(`
    <div class="modal-title">Language</div>
    ${[['en','🇺🇸 English'],['ru','🇷🇺 Русский'],['es','🇪🇸 Español'],['uk','🇺🇦 Українська'],['de','🇩🇪 Deutsch'],['fr','🇫🇷 Français'],['zh','🇨🇳 中文']].map(([l,label]) =>
      `<div class="settings-row" onclick="saveLang('${l}')">
        <span class="row-label">${label}</span>
        ${state.user?.language===l?'<span style="color:var(--btn)">✓</span>':''}
      </div>`
    ).join('')}`);
}

async function saveLang(lang) {
  haptic('medium');
  try {
    await put('/settings', { language: lang });
    if (state.user) state.user.language = lang;
    toast('✅ Language updated'); closeModal();
    await renderSettings(document.getElementById('content'));
  } catch (e) { toast('❌ '+e.message); }
}

function changeCurrency() {
  openModal(`
    <div class="modal-title">Currency</div>
    ${['USD','EUR','GBP','RUB','CAD','AUD','UAH','PLN'].map(c =>
      `<div class="settings-row" onclick="saveCurrency('${c}')">
        <span class="row-label">${c} ${currSymbol(c)}</span>
        ${state.user?.currency===c?'<span style="color:var(--btn)">✓</span>':''}
      </div>`
    ).join('')}`);
}

async function saveCurrency(cur) {
  haptic('medium');
  try {
    await put('/settings', { currency: cur });
    if (state.user) state.user.currency = cur;
    toast('✅ Currency updated'); closeModal();
    await renderSettings(document.getElementById('content'));
  } catch (e) { toast('❌ '+e.message); }
}

function showInviteCode() {
  haptic('light');
  const code = state.user?.invite_code || '—';
  openModal(`
    <div class="modal-title">Invite to Family</div>
    <div class="invite-code-box">
      <div class="invite-code" onclick="copyInvite('${code}')">${code}</div>
      <div class="invite-hint">Tap code to copy · Share with family members</div>
    </div>
    <div class="btn-wrap" style="padding-bottom:16px">
      <button class="btn btn-primary" onclick="copyInvite('${code}')">📋 Copy Code</button></div>`);
}

function copyInvite(code) {
  haptic('medium');
  navigator.clipboard?.writeText(code).then(() => toast('📋 Copied!'));
}

async function exportCSV() {
  haptic('light');
  toast('⏳ Preparing export…');
  try {
    const r    = await api('/export/csv');
    const blob = await r.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = `transactions_${new Date().toISOString().split('T')[0]}.csv`;
    a.click(); URL.revokeObjectURL(url);
    toast('✅ Exported!');
  } catch (e) { toast('❌ '+e.message); }
}

// ─── Modal helpers ─────────────────────────────────────────────────────────
function openModal(html) {
  document.getElementById('modal-content').innerHTML = html;
  document.getElementById('modal').classList.add('open');
  tg?.BackButton?.show();
  tg?.BackButton?.onClick(closeModal);
}
function setModalContent(html) {
  document.getElementById('modal-content').innerHTML = html;
}
function closeModal(evt) {
  if (evt && evt.target !== document.getElementById('modal')) return;
  document.getElementById('modal').classList.remove('open');
  tg?.BackButton?.hide();
  tg?.BackButton?.offClick(closeModal);
}

// ─── Init ──────────────────────────────────────────────────────────────────
(async () => {
  try {
    const [user, cats] = await Promise.all([
      get('/me').catch(() => null),
      get('/categories').catch(() => []),
    ]);
    if (user) {
      state.user = user;
      state.categories = cats;
      document.getElementById('user-avatar').textContent = user.name[0].toUpperCase();
    }
  } catch (_) {}
  navigate('dashboard');
})();

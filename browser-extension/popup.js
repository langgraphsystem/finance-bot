/* Finance Bot — Session Saver extension popup logic. */

const statusEl = document.getElementById('status');
const saveBtnEl = document.getElementById('saveBtn');
const domainEl = document.getElementById('currentDomain');
const cookieCountEl = document.getElementById('cookieCount');
const apiUrlEl = document.getElementById('apiUrl');
const tokenEl = document.getElementById('token');
const saveApiBtnEl = document.getElementById('saveApiBtn');
const checkConnectionBtnEl = document.getElementById('checkConnectionBtn');
const connectionInfoEl = document.getElementById('connectionInfo');
const savedListEl = document.getElementById('savedList');
const connectAmazonRelayBtnEl = document.getElementById('connectAmazonRelayBtn');

let currentDomain = '';
let currentCookies = [];
const AMAZON_RELAY_PROVIDER = 'relay.amazon.com';

const COOKIE_DOMAIN_ALIASES = {
  'relay.amazon.com': ['relay.amazon.com', 'amazon.com'],
};

function showStatus(msg, type) {
  statusEl.textContent = msg;
  statusEl.className = 'status ' + type;
}

function clearStatus() {
  statusEl.className = 'status';
  statusEl.textContent = '';
}

function normalizeApiUrl(value) {
  const trimmed = (value || '').trim().replace(/\/+$/, '');
  if (!trimmed) return '';
  if (trimmed.endsWith('/webhook')) {
    return trimmed.slice(0, -'/webhook'.length);
  }
  if (trimmed.endsWith('/api/ext')) {
    return trimmed.slice(0, -'/api/ext'.length);
  }
  return trimmed;
}

function normalizeDomain(value) {
  const raw = (value || '').trim().toLowerCase().replace(/^https?:\/\//, '');
  const domain = raw.split('/')[0].replace(/^www\./, '');
  if (!domain) return '';
  if (domain === 'uber.com' || domain.endsWith('.uber.com')) {
    return 'uber.com';
  }
  if (domain === 'lyft.com' || domain.endsWith('.lyft.com')) {
    return 'lyft.com';
  }
  if (domain === 'booking.com' || domain.endsWith('.booking.com')) {
    return 'booking.com';
  }
  if (domain === 'relay.amazon.com' || domain.endsWith('.relay.amazon.com')) {
    return 'relay.amazon.com';
  }
  return domain;
}

function getCookieDomains(domain) {
  return COOKIE_DOMAIN_ALIASES[domain] || [domain];
}

async function loadCookiesForDomain(domain) {
  const cookies = [];
  const seen = new Set();

  for (const cookieDomain of getCookieDomains(domain)) {
    const exactCookies = await chrome.cookies.getAll({ domain: cookieDomain });
    const dotCookies = await chrome.cookies.getAll({ domain: '.' + cookieDomain });

    for (const cookie of exactCookies.concat(dotCookies)) {
      const key = cookie.name + '|' + cookie.domain + '|' + cookie.path;
      if (seen.has(key)) continue;
      seen.add(key);
      cookies.push(cookie);
    }
  }

  return cookies;
}

function setConnectionInfo(text) {
  connectionInfoEl.textContent = text;
}

async function openConnectFlow(provider, label) {
  clearStatus();
  const settings = await chrome.storage.sync.get(['apiUrl', 'token']);
  const apiUrl = normalizeApiUrl(settings.apiUrl || '');
  const token = (settings.token || '').trim();

  if (!apiUrl || !token) {
    showStatus('Set API URL and token first', 'error');
    return;
  }

  const connectUrl = apiUrl + '/api/ext/connect?provider=' + encodeURIComponent(provider);
  await chrome.tabs.create({ url: connectUrl, active: true });
  showStatus(
    label + ' opened. Finish login in Chrome and the session will save automatically.',
    'success'
  );
}

// Load saved settings
chrome.storage.sync.get(['apiUrl', 'token'], (data) => {
  if (data.apiUrl) apiUrlEl.value = data.apiUrl;
  if (data.token) tokenEl.value = data.token;
  if (data.apiUrl && data.token) {
    checkConnection();
    loadSessions();
  }
});

// Save settings button
saveApiBtnEl.addEventListener('click', () => {
  const apiUrl = normalizeApiUrl(apiUrlEl.value);
  const token = tokenEl.value.trim();
  if (!apiUrl || !token) {
    showStatus('Enter both API URL and token', 'error');
    return;
  }
  apiUrlEl.value = apiUrl;
  chrome.storage.sync.set({ apiUrl, token }, () => {
    showStatus('Settings saved', 'success');
    checkConnection();
    loadSessions();
  });
});

checkConnectionBtnEl.addEventListener('click', () => {
  checkConnection();
});

connectAmazonRelayBtnEl.addEventListener('click', () => {
  openConnectFlow(AMAZON_RELAY_PROVIDER, 'Amazon Relay');
});

// Get current tab and its cookies
async function init() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url) {
      domainEl.textContent = 'No active tab';
      return;
    }

    const url = new URL(tab.url);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') {
      domainEl.textContent = 'Not a website';
      return;
    }

    currentDomain = normalizeDomain(url.hostname);
    domainEl.textContent = currentDomain;

    currentCookies = await loadCookiesForDomain(currentDomain);

    cookieCountEl.textContent = currentCookies.length + ' cookies found';
    saveBtnEl.disabled = currentCookies.length === 0;
  } catch (err) {
    domainEl.textContent = 'Error loading tab';
    console.error(err);
  }
}

// Save session button
saveBtnEl.addEventListener('click', async () => {
  clearStatus();
  const settings = await chrome.storage.sync.get(['apiUrl', 'token']);
  if (!settings.apiUrl || !settings.token) {
    showStatus('Set API URL and token first', 'error');
    return;
  }

  saveBtnEl.disabled = true;
  saveBtnEl.textContent = 'Saving...';

  // Convert Chrome cookies to Playwright format
  const playwrightCookies = currentCookies.map(c => ({
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path || '/',
    expires: c.expirationDate || -1,
    httpOnly: c.httpOnly || false,
    secure: c.secure || false,
    sameSite: c.sameSite === 'unspecified' ? 'None' :
              c.sameSite.charAt(0).toUpperCase() + c.sameSite.slice(1),
  }));

  try {
    const resp = await fetch(settings.apiUrl + '/api/ext/session', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + settings.token,
      },
      body: JSON.stringify({
        site: currentDomain,
        cookies: playwrightCookies,
      }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || 'Server error ' + resp.status);
    }

    const data = await resp.json();
    showStatus('Session saved for ' + data.site, 'success');
    loadSessions();
  } catch (err) {
    showStatus('Failed: ' + err.message, 'error');
  } finally {
    saveBtnEl.disabled = false;
    saveBtnEl.textContent = 'Save Session';
  }
});

// Load saved sessions from API
async function loadSessions() {
  const settings = await chrome.storage.sync.get(['apiUrl', 'token']);
  if (!settings.apiUrl || !settings.token) return;

  try {
    const resp = await fetch(settings.apiUrl + '/api/ext/sessions', {
      headers: { 'Authorization': 'Bearer ' + settings.token },
    });

    if (!resp.ok) return;

    const data = await resp.json();
    if (!data.sessions || data.sessions.length === 0) {
      savedListEl.innerHTML = '<div class="info">No saved sessions</div>';
      return;
    }

    savedListEl.innerHTML = data.sessions.map(s =>
      `<div class="saved-item">
        <span class="site">${s.site}</span>
        <span class="count">${s.cookie_count} cookies</span>
        <button class="delete-btn" data-site="${s.site}">×</button>
      </div>`
    ).join('');

    // Add delete handlers
    savedListEl.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const site = btn.dataset.site;
        try {
          await fetch(
            settings.apiUrl + '/api/ext/session/' + encodeURIComponent(site),
            {
              method: 'DELETE',
              headers: { 'Authorization': 'Bearer ' + settings.token },
            }
          );
          loadSessions();
        } catch (err) {
          console.error('Delete failed:', err);
        }
      });
    });
  } catch (err) {
    console.error('Failed to load sessions:', err);
  }
}

async function checkConnection() {
  const settings = await chrome.storage.sync.get(['apiUrl', 'token']);
  if (!settings.apiUrl || !settings.token) {
    setConnectionInfo('Not connected');
    return;
  }

  try {
    const resp = await fetch(normalizeApiUrl(settings.apiUrl) + '/api/ext/status', {
      headers: { 'Authorization': 'Bearer ' + settings.token },
    });

    if (!resp.ok) {
      setConnectionInfo('Connection failed');
      return;
    }

    const data = await resp.json();
    const sites = data.sites && data.sites.length
      ? '\nSaved sites: ' + data.sites.join(', ')
      : '\nSaved sites: none';
    setConnectionInfo(
      'Connected\nUser: ' + data.user_id.slice(0, 8) +
      '\nSessions: ' + data.session_count +
      sites
    );
  } catch (err) {
    setConnectionInfo('Connection failed');
    console.error('Connection check failed:', err);
  }
}

init();

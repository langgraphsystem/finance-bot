/* Finance Bot — Session Saver extension popup logic. */

const statusEl = document.getElementById('status');
const saveBtnEl = document.getElementById('saveBtn');
const domainEl = document.getElementById('currentDomain');
const cookieCountEl = document.getElementById('cookieCount');
const apiUrlEl = document.getElementById('apiUrl');
const tokenEl = document.getElementById('token');
const saveApiBtnEl = document.getElementById('saveApiBtn');
const savedListEl = document.getElementById('savedList');

let currentDomain = '';
let currentCookies = [];

function showStatus(msg, type) {
  statusEl.textContent = msg;
  statusEl.className = 'status ' + type;
}

function clearStatus() {
  statusEl.className = 'status';
  statusEl.textContent = '';
}

// Load saved settings
chrome.storage.sync.get(['apiUrl', 'token'], (data) => {
  if (data.apiUrl) apiUrlEl.value = data.apiUrl;
  if (data.token) tokenEl.value = data.token;
  if (data.apiUrl && data.token) {
    loadSessions();
  }
});

// Save settings button
saveApiBtnEl.addEventListener('click', () => {
  const apiUrl = apiUrlEl.value.trim().replace(/\/+$/, '');
  const token = tokenEl.value.trim();
  if (!apiUrl || !token) {
    showStatus('Enter both API URL and token', 'error');
    return;
  }
  chrome.storage.sync.set({ apiUrl, token }, () => {
    showStatus('Settings saved', 'success');
    loadSessions();
  });
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

    currentDomain = url.hostname.replace(/^www\./, '');
    domainEl.textContent = currentDomain;

    // Get cookies for this domain
    currentCookies = await chrome.cookies.getAll({ domain: currentDomain });

    // Also try with dot prefix for broader coverage
    const dotCookies = await chrome.cookies.getAll({ domain: '.' + currentDomain });
    const seen = new Set(currentCookies.map(c => c.name + '|' + c.domain));
    for (const c of dotCookies) {
      const key = c.name + '|' + c.domain;
      if (!seen.has(key)) {
        currentCookies.push(c);
        seen.add(key);
      }
    }

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

init();

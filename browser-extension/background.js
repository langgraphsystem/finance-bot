/* Finance Bot — Session Saver background service worker. */

const CONNECT_PATH = '/api/ext/connect';
const RETURN_PAYLOAD = 'browser_connect';
const SUPPORTED_PROVIDERS = new Set(['uber.com', 'lyft.com', 'booking.com', 'relay.amazon.com']);
const AUTH_PATH_HINTS = [
  '/login',
  '/signin',
  '/sign-in',
  '/auth',
  '/challenge',
  '/verify',
  '/mfa',
  '/otp',
  '/ap/signin',
];
const COOKIE_DOMAIN_ALIASES = {
  'relay.amazon.com': ['relay.amazon.com', 'amazon.com'],
};

chrome.runtime.onInstalled.addListener(() => {
  console.log('Finance Bot Session Saver installed');
});

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

function isAuthLikePath(pathname) {
  const lowered = (pathname || '').toLowerCase();
  return AUTH_PATH_HINTS.some(hint => lowered.includes(hint));
}

async function getSettings() {
  const syncData = await chrome.storage.sync.get(['apiUrl', 'token']);
  const apiUrl = normalizeApiUrl(syncData.apiUrl || '');
  const token = (syncData.token || '').trim();
  return { apiUrl, token };
}

async function getStatus(settings) {
  const response = await fetch(settings.apiUrl + '/api/ext/status', {
    headers: { Authorization: 'Bearer ' + settings.token },
  });
  if (!response.ok) {
    throw new Error('status ' + response.status);
  }
  return response.json();
}

function getCookieDomains(domain) {
  return COOKIE_DOMAIN_ALIASES[domain] || [domain];
}

async function getCookiesForDomain(domain) {
  const seen = new Set();
  const cookies = [];

  for (const cookieDomain of getCookieDomains(domain)) {
    const exactCookies = await chrome.cookies.getAll({ domain: cookieDomain });
    const dottedCookies = await chrome.cookies.getAll({ domain: '.' + cookieDomain });

    for (const cookie of exactCookies.concat(dottedCookies)) {
      const key = cookie.name + '|' + cookie.domain + '|' + cookie.path;
      if (seen.has(key)) continue;
      seen.add(key);
      cookies.push({
        name: cookie.name,
        value: cookie.value,
        domain: cookie.domain,
        path: cookie.path || '/',
        expires: cookie.expirationDate || -1,
        httpOnly: cookie.httpOnly || false,
        secure: cookie.secure || false,
        sameSite: cookie.sameSite === 'unspecified'
          ? 'None'
          : cookie.sameSite.charAt(0).toUpperCase() + cookie.sameSite.slice(1),
      });
    }
  }

  return cookies;
}

async function saveSession(settings, domain, cookies) {
  const response = await fetch(settings.apiUrl + '/api/ext/session', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + settings.token,
    },
    body: JSON.stringify({ site: domain, cookies }),
  });
  if (!response.ok) {
    throw new Error('save ' + response.status);
  }
  return response.json();
}

async function redirectToTelegram(tabId, botUsername) {
  if (!botUsername) return;
  const httpsUrl = 'https://t.me/' + botUsername + '?start=' + RETURN_PAYLOAD;
  await chrome.tabs.update(tabId, { url: httpsUrl });
}

async function maybeCompletePendingConnect(tabId, urlString) {
  const pendingConnect = (await chrome.storage.local.get(['pendingConnect'])).pendingConnect;
  if (!pendingConnect || !pendingConnect.provider) {
    return;
  }

  let url;
  try {
    url = new URL(urlString);
  } catch (error) {
    console.error('Invalid tab URL', error);
    return;
  }

  const domain = normalizeDomain(url.hostname);
  if (!domain || domain !== pendingConnect.provider) {
    return;
  }
  if (isAuthLikePath(url.pathname)) {
    return;
  }

  const settings = await getSettings();
  if (!settings.apiUrl || !settings.token) {
    return;
  }

  try {
    const cookies = await getCookiesForDomain(domain);
    if (cookies.length === 0) {
      return;
    }

    const saved = await saveSession(settings, domain, cookies);
    const status = await getStatus(settings);
    await chrome.storage.local.set({
      pendingConnect: null,
      botUsername: status.bot_username || '',
      lastSavedSite: saved.site,
    });
    await redirectToTelegram(tabId, status.bot_username || '');
  } catch (error) {
    console.error('Auto-save failed', error);
  }
}

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  const currentUrl = changeInfo.url || tab.url;
  if (!currentUrl) {
    return;
  }

  const settings = await getSettings();
  if (!settings.apiUrl || !settings.token) {
    return;
  }

  const connectPrefix = settings.apiUrl + CONNECT_PATH;
  if (currentUrl.startsWith(connectPrefix)) {
    try {
      const url = new URL(currentUrl);
      const provider = normalizeDomain(url.searchParams.get('provider') || '');
      if (provider && SUPPORTED_PROVIDERS.has(provider)) {
        await chrome.storage.local.set({
          pendingConnect: {
            provider,
            startedAt: Date.now(),
          },
        });
      }
    } catch (error) {
      console.error('Failed to initialize connect flow', error);
    }
    return;
  }

  if (changeInfo.status === 'complete') {
    await maybeCompletePendingConnect(tabId, currentUrl);
  }
});

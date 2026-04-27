const API_ORIGIN = import.meta.env.VITE_API_URL || '';
const BASE = API_ORIGIN;

function toWebSocketBase(origin) {
  if (!origin) {
    if (typeof window !== 'undefined') {
      return `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
    }
    return 'ws://localhost:5173';
  }
  return origin.startsWith('https://')
    ? origin.replace('https://', 'wss://')
    : origin.replace('http://', 'ws://');
}

const WS_BASE = toWebSocketBase(API_ORIGIN);

function emitDebug(location, message, data, hypothesisId) {
  // #region agent log
  fetch('http://127.0.0.1:7350/ingest/94dadc8f-cafb-4a51-8321-2f84e03534d2',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'e3292d'},body:JSON.stringify({sessionId:'e3292d',runId:'initial',hypothesisId,location,message,data,timestamp:Date.now()})}).catch(()=>{});
  // #endregion
}

async function request(path, options = {}, method = 'GET') {
  const url = `${BASE}${path}`;
  const response = await fetch(url, options);
  try {
    const payload = await response.json();
    emitDebug('frontend/src/lib/api.js:request', 'api response parsed', { method, path, ok: response.ok }, 'H2');
    if (!response.ok) {
      emitDebug('frontend/src/lib/api.js:request', 'non-ok api response', { method, path, status: response.status }, 'H2');
      throw new Error(payload?.detail || `Request failed with status ${response.status}`);
    }
    return payload;
  } catch (err) {
    emitDebug('frontend/src/lib/api.js:request', 'json parse failed', { method, path, error: String(err) }, 'H2');
    throw err;
  }
}

export const api = {
  get: (path) => request(path, {}, 'GET'),
  post: (path, body) => request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }, 'POST'),
  put: (path, body) => request(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }, 'PUT'),
  delete: (path) => request(path, { method: 'DELETE' }, 'DELETE'),
};

export const WS_URL = `${WS_BASE}/ws`;

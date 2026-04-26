const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001';
const WS_BASE = BASE.replace('http', 'ws');

export const api = {
  get: (path) => fetch(`${BASE}${path}`).then(r => r.json()),
  post: (path, body) => fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(r => r.json()),
  put: (path, body) => fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(r => r.json()),
  delete: (path) => fetch(`${BASE}${path}`, { method: 'DELETE' }).then(r => r.json()),
};

export const WS_URL = `${WS_BASE}/ws`;

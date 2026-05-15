const DEFAULT_TIMEOUT_MS = 30_000;

function withTimeout(promise, timeoutMs = DEFAULT_TIMEOUT_MS) {
  if (!timeoutMs || timeoutMs <= 0) return promise;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return Promise.race([
    promise(controller.signal).finally(() => clearTimeout(timer)),
    new Promise((_, reject) => {
      controller.signal.addEventListener('abort', () => reject(new Error('Request timeout')));
    }),
  ]);
}

async function request(path, { method = 'GET', baseUrl = '', json, headers, timeoutMs } = {}) {
  const url = baseUrl ? new URL(path, baseUrl).toString() : path;

  return withTimeout(
    (signal) =>
      fetch(url, {
        method,
        credentials: 'include',
        headers: {
          ...(json ? { 'Content-Type': 'application/json' } : null),
          ...(headers || null),
        },
        body: json ? JSON.stringify(json) : undefined,
        signal,
      }),
    timeoutMs,
  );
}

export async function requestJson(path, options = {}) {
  const res = await request(path, options);
  const contentType = res.headers.get('content-type') || '';
  const body = contentType.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    const message = typeof body === 'string' ? body : body?.error || body?.message || res.statusText;
    const error = new Error(message || `HTTP ${res.status}`);
    error.status = res.status;
    error.body = body;
    throw error;
  }
  return body;
}

export function makeApiBase(prefix = '/api') {
  return {
    get: (p, opts) => requestJson(`${prefix}${p}`, { ...opts, method: 'GET' }),
    post: (p, json, opts) => requestJson(`${prefix}${p}`, { ...opts, method: 'POST', json }),
    del: (p, opts) => requestJson(`${prefix}${p}`, { ...opts, method: 'DELETE' }),
  };
}

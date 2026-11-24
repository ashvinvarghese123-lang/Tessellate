export const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

export const STD: Array<[string, string]> = [
  ['09:00', '10:00'],
  ['10:00', '11:00'],
  ['11:15', '12:15'],
  ['12:15', '13:15'],
  ['14:00', '15:00'],
  ['15:00', '16:00'],
];

export const tmn = (t: string) => {
  if (!t) return 0;
  const [h, m] = t.split(':').map(Number);
  return (h || 0) * 60 + (m || 0);
};

export const esc = (s: any) =>
  String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] || c));

export interface ApiOptions extends Omit<RequestInit, 'body'> {
  body?: any;
}

export async function api<T = any>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  let body: BodyInit | null | undefined = undefined;

  if (options.body !== undefined && options.body !== null) {
    if (typeof options.body === 'object' && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
      body = JSON.stringify(options.body);
    } else {
      body = options.body;
    }
  }

  const response = await fetch(path, {
    credentials: 'include',
    ...options,
    headers,
    body,
  });

  let data: any = {};
  try {
    data = await response.json();
  } catch {
    // Empty body or non-JSON response
  }

  if (!response.ok) {
    if (response.status === 401) {
      if (path.startsWith('/api/registry')) {
        if (!window.location.pathname.includes('registry-login')) {
          window.location.replace('/registry-login.html');
        }
      } else {
        if (!window.location.pathname.includes('login')) {
          window.location.replace('/login.html');
        }
      }
    }
    const message =
      typeof data.detail === 'string'
        ? data.detail
        : Array.isArray(data.detail)
        ? data.detail.map((x: any) => x.msg || JSON.stringify(x)).join(', ')
        : 'Something went wrong. Please try again.';
    throw new Error(message);
  }

  return data as T;
}

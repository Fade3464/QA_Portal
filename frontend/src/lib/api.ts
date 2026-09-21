type ApiErrorShape = { error?: { detail?: unknown }; detail?: unknown };

let csrfToken = '';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export function setCsrfToken(token: string) {
  csrfToken = token;
}

function errorMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(errorMessage).filter(Boolean).join(' ');
  if (detail && typeof detail === 'object') {
    return Object.values(detail).map(errorMessage).filter(Boolean).join(' ');
  }
  return '';
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (csrfToken && !['GET', 'HEAD', 'OPTIONS'].includes((options.method ?? 'GET').toUpperCase())) {
    headers.set('X-CSRFToken', csrfToken);
  }
  const response = await fetch(path, { ...options, headers, credentials: 'include' });
  if (response.status === 204) return undefined as T;
  const body = (await response.json().catch(() => ({}))) as ApiErrorShape;
  if (!response.ok) {
    const detail = body.error?.detail ?? body.detail;
    throw new ApiError(errorMessage(detail) || 'Something went wrong. Please try again.', response.status);
  }
  return body as T;
}

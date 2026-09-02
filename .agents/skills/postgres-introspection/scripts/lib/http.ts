// A small HTTP source for introspecting network services (PostgREST now, the Fastify gateway
// later). Keeps the fetch and timeout details in one place, mirroring how lib/db wraps the
// wire-protocol source.

const timeoutMs = 8000;

export async function getJson(url: string, headers: Record<string, string> = {}): Promise<unknown> {
  const response = await fetchWithTimeout(url, headers);
  if (!response.ok) {
    throw new Error(`GET ${url} returned ${response.status}`);
  }
  return response.json();
}

// Return the HTTP status code, or 0 if the request fails. Used for health probes that should
// report unreachable rather than throw.
export async function getStatus(url: string): Promise<number> {
  try {
    const response = await fetchWithTimeout(url);
    return response.status;
  } catch {
    return 0;
  }
}

async function fetchWithTimeout(url: string, headers: Record<string, string> = {}): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { headers, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

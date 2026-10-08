/**
 * API base URL for requests made from the browser.
 *
 * NEXT_PUBLIC_DD_API_URL wins when set. Through the Caddy proxy (no port in the address)
 * the API shares the page's origin. Otherwise it is the page's host on the API port
 * (http://localhost:3100 -> http://localhost:4000), so no IP is ever hard-coded.
 */
const API_PORT = process.env.NEXT_PUBLIC_DD_API_PORT ?? "4000";

export function browserApiBase(): string {
  if (process.env.NEXT_PUBLIC_DD_API_URL) return process.env.NEXT_PUBLIC_DD_API_URL;
  if (typeof window === "undefined") return `http://127.0.0.1:${API_PORT}`;
  // Behind the Caddy proxy the API is on the same origin. The API itself never serves HTTPS,
  // so an https page (or one on the default port) is always proxied.
  if (window.location.protocol === "https:" || !window.location.port) return window.location.origin;
  return `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;
}

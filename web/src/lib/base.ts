/** Path the SPA lives under: "/fin" behind `tailscale serve --set-path /fin`, "" when opened
 *  directly. The API injects the configured prefix into index.html; it only applies when the
 *  browser URL actually starts with it. */
const prefix = document.querySelector<HTMLMetaElement>('meta[name="fin-prefix"]')?.content ?? "";
const path = location.pathname;
export const BASE = prefix && (path === prefix || path.startsWith(prefix + "/")) ? prefix : "";

/** Cloudflare Worker boundary for the private, read-only reference surface. */
import handler from "vinext/server/app-router-entry";

type WorkerEnv = NonNullable<Parameters<typeof handler.fetch>[1]>;
type WorkerContext = NonNullable<Parameters<typeof handler.fetch>[2]>;

const SECURITY_HEADERS = {
  "Content-Security-Policy": [
    "default-src 'self'",
    "base-uri 'self'",
    "connect-src 'none'",
    "font-src 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "img-src 'self' data:",
    "media-src 'none'",
    "object-src 'none'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "worker-src 'self'",
  ].join("; "),
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Resource-Policy": "same-origin",
  "Permissions-Policy":
    "accelerometer=(), autoplay=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
} as const;

function harden(request: Request, response: Response): Response {
  const hardened = new Response(response.body, response);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    hardened.headers.set(name, value);
  }

  const contentType = hardened.headers.get("content-type") ?? "";
  if (/^text\/html\b/i.test(contentType)) {
    hardened.headers.set(
      "Cache-Control",
      "private, no-cache, no-store, must-revalidate",
    );
  }
  if (new URL(request.url).pathname.startsWith("/atlas-projection/")) {
    hardened.headers.set("Cache-Control", "private, no-cache, no-store, must-revalidate");
  }
  return hardened;
}

async function compressedProjectionModule(
  request: Request,
  env: WorkerEnv | undefined,
): Promise<Response | null> {
  const url = new URL(request.url);
  if (
    !env?.ASSETS ||
    !["GET", "HEAD"].includes(request.method) ||
    !url.pathname.startsWith("/atlas-projection/") ||
    !url.pathname.endsWith(".mjs")
  ) {
    return null;
  }

  const compressedUrl = new URL(url);
  compressedUrl.pathname = `${url.pathname}.gz`;
  const compressed = await env.ASSETS.fetch(
    new Request(compressedUrl, { method: request.method }),
  );
  if (!compressed.ok) return null;

  const headers = new Headers(compressed.headers);
  headers.set("Content-Encoding", "gzip");
  headers.set("Content-Type", "text/javascript; charset=utf-8");
  headers.set("Vary", "Accept-Encoding");
  return new Response(compressed.body, {
    status: compressed.status,
    statusText: compressed.statusText,
    headers,
  });
}

const worker = {
  async fetch(
    request: Request,
    env: WorkerEnv,
    ctx: WorkerContext,
  ): Promise<Response> {
    const compressed = await compressedProjectionModule(request, env);
    return harden(request, compressed ?? (await handler.fetch(request, env, ctx)));
  },
};

export default worker;

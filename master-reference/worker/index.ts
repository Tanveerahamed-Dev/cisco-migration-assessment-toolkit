/** Cloudflare Worker boundary for the private, read-only reference surface. */
import handler from "vinext/server/app-router-entry";

type WorkerEnv = NonNullable<Parameters<typeof handler.fetch>[1]>;
type WorkerContext = NonNullable<Parameters<typeof handler.fetch>[2]>;
type CloudflareResponseInit = ResponseInit & {
  encodeBody?: "automatic" | "manual";
};
type ProjectionResponse = {
  precompressed: boolean;
  response: Response;
};

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

function harden(
  request: Request,
  response: Response,
  encodeBody: "automatic" | "manual" = "automatic",
): Response {
  const init: CloudflareResponseInit = {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
    encodeBody,
  };
  const hardened = new Response(response.body, init);
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
): Promise<ProjectionResponse | null> {
  const url = new URL(request.url);
  const projectionModule =
    url.pathname.startsWith("/atlas-projection/") && url.pathname.endsWith(".mjs");
  if (!projectionModule) return null;

  const error = (status: number, message: string): ProjectionResponse => ({
    precompressed: false,
    response: new Response(request.method === "HEAD" ? null : `${message}\n`, {
      status,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    }),
  });
  if (!["GET", "HEAD"].includes(request.method)) {
    const methodError = error(405, "Projection modules support only GET and HEAD");
    methodError.response.headers.set("Allow", "GET, HEAD");
    return methodError;
  }
  if (!env?.ASSETS) return error(503, "Projection asset binding is unavailable");

  const compressedUrl = new URL(url);
  compressedUrl.pathname = `${url.pathname}.gz`;
  let compressed: Response;
  try {
    compressed = await env.ASSETS.fetch(
      new Request(compressedUrl, { method: request.method }),
    );
  } catch {
    return error(502, "Projection asset lookup failed");
  }
  if (compressed.status === 404) return error(404, "Projection module not found");
  if (compressed.status !== 200) return error(502, "Projection asset lookup failed");
  if (request.method === "GET" && compressed.body === null) {
    return error(502, "Projection asset response was not an encoded module");
  }

  const upstreamEncoding = (
    compressed.headers.get("content-encoding") ?? ""
  ).trim().toLowerCase();
  const upstreamType = compressed.headers.get("content-type") ?? "";
  const encodedAssetType =
    /^application\/(?:gzip|x-gzip|octet-stream)(?:\s*;|$)/i.test(upstreamType);
  const preencodedJavaScriptType =
    /^(?:text|application)\/javascript(?:\s*;|$)/i.test(upstreamType);
  if (
    !["", "gzip"].includes(upstreamEncoding) ||
    (!encodedAssetType && !(upstreamEncoding === "gzip" && preencodedJavaScriptType))
  ) {
    return error(502, "Projection asset response was not an encoded module");
  }

  const headers = new Headers(compressed.headers);
  headers.set("Content-Encoding", "gzip");
  headers.set("Content-Type", "text/javascript; charset=utf-8");
  headers.set("Vary", "Accept-Encoding");
  return {
    precompressed: true,
    response: new Response(compressed.body, {
      status: compressed.status,
      statusText: compressed.statusText,
      headers,
    }),
  };
}

const worker = {
  async fetch(
    request: Request,
    env: WorkerEnv,
    ctx: WorkerContext,
  ): Promise<Response> {
    const projection = await compressedProjectionModule(request, env);
    if (projection) {
      return harden(
        request,
        projection.response,
        projection.precompressed ? "manual" : "automatic",
      );
    }
    return harden(request, await handler.fetch(request, env, ctx));
  },
};

export default worker;

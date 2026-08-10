/** Cloudflare Worker boundary for the private, read-only reference surface. */
import handler from "vinext/server/app-router-entry";

import { CANONICAL_GZIP_HEADER_BYTES } from "../build/gzip-contract.js";

type WorkerEnv = NonNullable<Parameters<typeof handler.fetch>[1]>;
type WorkerContext = NonNullable<Parameters<typeof handler.fetch>[2]>;
type ResponseBodyStream = NonNullable<Response["body"]>;
type CloudflareResponseInit = ResponseInit & {
  encodeBody?: "automatic" | "manual";
};
type ProjectionResponse = {
  precompressed: boolean;
  response: Response;
};
type ProjectionErrorCode =
  | "asset_body_missing"
  | "asset_lookup_exception"
  | "asset_metadata_invalid"
  | "asset_not_found"
  | "asset_representation_invalid"
  | "asset_status_invalid"
  | "binding_unavailable"
  | "method_not_allowed";

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

async function replayCanonicalGzip(
  body: ResponseBodyStream,
): Promise<ResponseBodyStream | null> {
  let reader: ReadableStreamDefaultReader<Uint8Array<ArrayBuffer>> | null = null;
  const bufferedChunks: Uint8Array<ArrayBuffer>[] = [];
  const prefix = new Uint8Array(CANONICAL_GZIP_HEADER_BYTES.length);
  let prefixBytes = 0;
  let reachedEnd = false;

  try {
    reader = body.getReader();
    while (prefixBytes < prefix.byteLength) {
      const next = await reader.read();
      if (next.done) {
        reachedEnd = true;
        break;
      }
      if (next.value.byteLength === 0) continue;
      bufferedChunks.push(next.value);
      const copied = Math.min(next.value.byteLength, prefix.byteLength - prefixBytes);
      prefix.set(next.value.subarray(0, copied), prefixBytes);
      prefixBytes += copied;
    }
  } catch {
    if (reader) {
      try {
        await reader.cancel();
      } catch {
        // The categorical caller error is the only safe disclosure.
      }
    }
    return null;
  }

  if (!reader) return null;

  const canonical =
    prefixBytes === CANONICAL_GZIP_HEADER_BYTES.length &&
    CANONICAL_GZIP_HEADER_BYTES.every((value, index) => prefix[index] === value);
  if (!canonical) {
    try {
      await reader.cancel();
    } catch {
      // The categorical caller error is the only safe disclosure.
    }
    return null;
  }

  const replayReader = reader;
  return new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      for (const chunk of bufferedChunks) controller.enqueue(chunk);
      if (reachedEnd) controller.close();
    },
    async pull(controller) {
      try {
        const next = await replayReader.read();
        if (next.done) controller.close();
        else controller.enqueue(next.value);
      } catch {
        try {
          await replayReader.cancel();
        } catch {
          // The downstream sees only the stable categorical stream error.
        }
        controller.error(new Error("Atlas projection stream failed"));
      }
    },
    async cancel() {
      try {
        await replayReader.cancel();
      } catch {
        // Cancellation reasons and upstream failures are never disclosed.
      }
    },
  });
}

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

  const error = (
    status: number,
    message: string,
    code: ProjectionErrorCode,
    upstream?: Response,
  ): ProjectionResponse => {
    if (status === 502) {
      const encodingCategory = (value: string | null): string => {
        const normalized = value?.trim().toLowerCase() ?? "";
        if (!normalized) return "missing";
        if (normalized === "gzip") return "gzip";
        if (normalized === "br") return "br";
        if (normalized === "identity") return "identity";
        if (normalized.includes(",")) return "multiple";
        return "other";
      };
      const typeCategory = (value: string | null): string => {
        const normalized = value?.trim().toLowerCase() ?? "";
        if (!normalized) return "missing";
        if (/^application\/(?:gzip|x-gzip|octet-stream)(?:\s*;|$)/.test(normalized)) {
          return "encoded_asset";
        }
        if (/^(?:text|application)\/javascript(?:\s*;|$)/.test(normalized)) {
          return "javascript";
        }
        if (/^text\/html(?:\s*;|$)/.test(normalized)) return "html";
        if (/^text\/plain(?:\s*;|$)/.test(normalized)) return "text_plain";
        if (/^application\/json(?:\s*;|$)/.test(normalized)) return "json";
        if (/^application\/null(?:\s*;|$)/.test(normalized)) return "application_null";
        return "other";
      };
      console.error(`atlas_projection_rejected ${JSON.stringify({
        code,
        contentEncoding: encodingCategory(
          upstream?.headers.get("content-encoding") ?? null,
        ),
        contentType: typeCategory(upstream?.headers.get("content-type") ?? null),
        hasBody: upstream ? upstream.body !== null : null,
        method: request.method,
        upstreamStatus: upstream?.status ?? null,
      })}`);
    }
    return {
      precompressed: false,
      response: new Response(request.method === "HEAD" ? null : `${message}\n`, {
        status,
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "X-Atlas-Projection-Error": code,
        },
      }),
    };
  };
  if (!["GET", "HEAD"].includes(request.method)) {
    const methodError = error(
      405,
      "Projection modules support only GET and HEAD",
      "method_not_allowed",
    );
    methodError.response.headers.set("Allow", "GET, HEAD");
    return methodError;
  }
  if (!env?.ASSETS) {
    return error(503, "Projection asset binding is unavailable", "binding_unavailable");
  }

  const compressedUrl = new URL(url);
  compressedUrl.pathname = `${url.pathname}.gz`;
  let compressed: Response;
  try {
    compressed = await env.ASSETS.fetch(
      new Request(compressedUrl, { method: request.method }),
    );
  } catch {
    return error(502, "Projection asset lookup failed", "asset_lookup_exception");
  }
  if (compressed.status === 404) {
    return error(404, "Projection module not found", "asset_not_found", compressed);
  }
  if (compressed.status !== 200) {
    return error(502, "Projection asset lookup failed", "asset_status_invalid", compressed);
  }
  if (request.method === "GET" && compressed.body === null) {
    return error(
      502,
      "Projection asset response was not an encoded module",
      "asset_body_missing",
      compressed,
    );
  }

  const upstreamEncoding = (
    compressed.headers.get("content-encoding") ?? ""
  ).trim().toLowerCase();
  const upstreamType = compressed.headers.get("content-type") ?? "";
  const encodedAssetType =
    /^application\/(?:gzip|x-gzip|octet-stream)(?:\s*;|$)/i.test(upstreamType);
  const preencodedJavaScriptType =
    /^(?:text|application)\/javascript(?:\s*;|$)/i.test(upstreamType);
  const metadataValid =
    (upstreamEncoding === "" &&
      (encodedAssetType || (request.method === "GET" && preencodedJavaScriptType))) ||
    (upstreamEncoding === "gzip" && (encodedAssetType || preencodedJavaScriptType));
  if (!metadataValid) {
    return error(
      502,
      "Projection asset response was not an encoded module",
      "asset_metadata_invalid",
      compressed,
    );
  }

  let responseBody = compressed.body;
  if (request.method === "GET" && upstreamEncoding === "") {
    const replay = await replayCanonicalGzip(responseBody!);
    if (!replay) {
      return error(
        502,
        "Projection asset response was not the canonical encoded representation",
        "asset_representation_invalid",
        compressed,
      );
    }
    responseBody = replay;
  }

  const headers = new Headers(compressed.headers);
  headers.set("Content-Encoding", "gzip");
  headers.set("Content-Type", "text/javascript; charset=utf-8");
  headers.set("Vary", "Accept-Encoding");
  return {
    precompressed: true,
    response: new Response(responseBody, {
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

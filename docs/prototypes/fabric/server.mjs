import { createServer } from "node:http";
import { readFile } from "node:fs/promises";

const FABRIC_HTML = new URL("./fabric.html", import.meta.url);
const ALLOWED_PATHS = new Set(["/", "/fabric.html"]);

function end(res, status, body = "", headers = {}) {
  const bytes = Buffer.from(body, "utf8");
  res.writeHead(status, {
    "Content-Type": "text/plain; charset=utf-8",
    "Content-Length": bytes.byteLength,
    ...headers,
  });
  res.end(bytes);
}

export function createFabricServer() {
  return createServer(async (req, res) => {
    if (req.method !== "GET" && req.method !== "HEAD") {
      end(res, 405, "method not allowed", { Allow: "GET, HEAD" });
      return;
    }

    const rawPath = (req.url ?? "").split("?", 1)[0];
    let pathname;
    try {
      pathname = decodeURIComponent(rawPath);
    } catch {
      end(res, 400, "bad request");
      return;
    }
    if (!ALLOWED_PATHS.has(pathname)) {
      end(res, 404, "not found");
      return;
    }

    try {
      const body = await readFile(FABRIC_HTML);
      res.writeHead(200, {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Length": body.byteLength,
      });
      res.end(req.method === "HEAD" ? undefined : body);
    } catch {
      end(res, 500, "unavailable");
    }
  });
}

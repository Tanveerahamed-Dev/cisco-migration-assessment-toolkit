import assert from "node:assert/strict";
import { request } from "node:http";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createFabricServer } from "../../../docs/prototypes/fabric/server.mjs";

function fetchFrom(server, path, method = "GET") {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("test server is not bound");
  return new Promise((resolve, reject) => {
    const req = request(
      { host: "127.0.0.1", port: address.port, path, method },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => resolve({
          status: res.statusCode,
          type: res.headers["content-type"],
          allow: res.headers.allow,
          body: Buffer.concat(chunks),
        }));
      },
    );
    req.on("error", reject);
    req.end();
  });
}

test("fabric verifier server serves only the fixed HTML asset", async () => {
  const server = createFabricServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const expected = await readFile(
      new URL("../../../docs/prototypes/fabric/fabric.html", import.meta.url),
    );
    for (const path of ["/", "/fabric.html", "/fabric.html?cache=1"]) {
      const response = await fetchFrom(server, path);
      assert.equal(response.status, 200, path);
      assert.equal(response.type, "text/html; charset=utf-8", path);
      assert.deepEqual(response.body, expected, path);
    }

    const head = await fetchFrom(server, "/fabric.html", "HEAD");
    assert.equal(head.status, 200);
    assert.equal(head.body.byteLength, 0);

    for (const path of [
      "/README.md",
      "/../README.md",
      "/%2e%2e/README.md",
      "/..%2fREADME.md",
      "/fabric.html/../README.md",
      "/%2ffabric.html",
    ]) {
      const response = await fetchFrom(server, path);
      assert.equal(response.status, 404, path);
    }
    assert.equal((await fetchFrom(server, "/%ZZ")).status, 400);
    for (const method of ["POST", "OPTIONS"]) {
      const response = await fetchFrom(server, "/fabric.html", method);
      assert.equal(response.status, 405, method);
      assert.equal(response.allow, "GET, HEAD", method);
    }
  } finally {
    await new Promise((resolve, reject) => server.close((error) => (
      error ? reject(error) : resolve()
    )));
  }
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  IMPORT_PROBE,
  childExitCode,
  selectInterpreter,
} from "../tools/graphify_mcp_launcher.mjs";

const candidate = (command) => ({ command, prefixArgs: [], key: command });

test("the probe performs a real import and stays off MCP stdout", () => {
  const calls = [];
  const selected = selectInterpreter(
    [candidate("broken"), candidate("working")],
    {
      cwd: "/repo",
      runner(command, args, options) {
        calls.push({ command, args, options });
        return { status: command === "working" ? 0 : 1 };
      },
    },
  );

  assert.equal(selected.command, "working");
  assert.deepEqual(
    calls.map(({ command }) => command),
    ["broken", "working"],
  );
  for (const call of calls) {
    assert.deepEqual(call.args, IMPORT_PROBE);
    assert.equal(call.options.stdio, "ignore");
  }
  assert.deepEqual(IMPORT_PROBE, ["-c", "import graphify.serve"]);
});

test("selection fails closed when every interpreter is broken", () => {
  const selected = selectInterpreter([candidate("broken")], {
    runner: () => ({ status: 1 }),
  });
  assert.equal(selected, null);
});

test("child exits and signals remain nonzero and conventional", () => {
  assert.equal(childExitCode(0, null), 0);
  assert.equal(childExitCode(7, null), 7);
  assert.equal(childExitCode(null, "SIGINT"), 130);
  assert.equal(childExitCode(null, "SIGTERM"), 143);
  assert.equal(childExitCode(null, "SIGHUP"), 1);
});

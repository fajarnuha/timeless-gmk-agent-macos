import assert from "node:assert/strict";
import timeless82 from "../hooks/pi.ts";

const handlers = {};
const calls = [];
timeless82({
  on(event, handler) { handlers[event] = handler; },
  async exec(python, args) { calls.push(args); },
});
const context = { sessionManager: { getSessionId: () => "test-session" } };
await handlers.agent_start({}, context);
assert.equal(calls.at(-1)[3], "start");
assert.equal(handlers.agent_end, undefined);
await handlers.agent_settled({ aborted: false }, context);
assert.equal(calls.at(-1)[3], "finish");
await handlers.session_shutdown({}, context);
assert.equal(calls.length, 2);
await handlers.agent_start({}, context);
await handlers.agent_settled({ aborted: true }, context);
assert.equal(calls.at(-1)[3], "cancel");
await handlers.agent_start({}, context);
await handlers.session_shutdown({}, context);
assert.equal(calls.at(-1)[3], "cancel");
console.log("Pi start, settlement, abort, and shutdown hooks passed");

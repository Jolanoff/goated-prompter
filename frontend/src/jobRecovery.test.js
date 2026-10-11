import { test } from "node:test";
import assert from "node:assert/strict";
import { adoptActiveJob } from "./jobRecovery.js";

function withFetch(handler, run) {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return run().finally(() => { globalThis.fetch = original; });
}

test("a conflict response's active job is adopted without another request", async () => {
  const received = [];
  await withFetch(() => { throw new Error("unexpected request"); }, () =>
    adoptActiveJob(Object.assign(new Error("busy"), { activeJob: { id: "a" } }), (job) => received.push(job)));
  assert.deepEqual(received, [{ id: "a" }]);
});

test("other failures check bootstrap for an active job", async () => {
  const received = [];
  const paths = [];
  await withFetch(async (path) => {
    paths.push(path);
    return { ok: true, json: async () => ({ active_job: { id: "b" } }) };
  }, () => adoptActiveJob(new Error("network"), (job) => received.push(job)));
  assert.deepEqual(paths, ["/api/bootstrap"]);
  assert.deepEqual(received, [{ id: "b" }]);
});

test("recovery failures are ignored and no job is adopted", async () => {
  const received = [];
  await withFetch(async () => { throw new Error("offline"); }, () =>
    adoptActiveJob(new Error("network"), (job) => received.push(job)));
  await withFetch(async () => ({ ok: true, json: async () => ({ active_job: null }) }), () =>
    adoptActiveJob(new Error("network"), (job) => received.push(job)));
  assert.deepEqual(received, []);
});

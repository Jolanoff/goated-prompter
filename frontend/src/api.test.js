import test from "node:test";
import assert from "node:assert/strict";
import { api } from "./api.js";

test("JSON transport honors bodyless DELETE and preserves default GET/POST", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    requests.push({ path, options });
    return { ok: true, json: async () => ({ ok: true }) };
  });
  await api("/bootstrap");
  await api("/jobs?kind=dataset", undefined, "DELETE");
  await api("/workspace/dataset", { input: "example" });
  assert.deepEqual(requests.map(({ options }) => options.method), ["GET", "DELETE", "POST"]);
  assert.equal(requests[1].options.body, undefined);
  assert.equal(requests[2].options.body, '{"input":"example"}');
});

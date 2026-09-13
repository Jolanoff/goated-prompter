const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../comfyui_web/goated_prompter/goated_prompter.js"), "utf8")
  .replace(/^import\s[\s\S]*?;\r?\n/gm, "");

function fixture() {
  let extension;
  let select;
  const requests = [];
  const context = vm.createContext({
    app: { registerExtension: (value) => { extension = value; } },
    api: { fetchApi: () => new Promise((resolve, reject) => requests.push({ resolve, reject })) },
    LiteGraph: { ContextMenu: function (_, options) { select = options.callback; } },
    DEFAULT_ACCENT: "#123456", SWATCHES: [], THEMES: ["Dark"], THEME_TOKENS: { Dark: {} },
    normalizeHex: (value) => value,
    buildAccentPalette: () => ({}), activeFill: () => "", activeForeground: () => "",
    drawPaletteIcon() {}, drawRound() {}, drawText() {}, hexToRgba() {}, ellipsize: (_, text) => text,
  });
  vm.runInContext(`${source}\nthis.frontend = { REFERENCE_SOURCES, WIDGET_NAMES, detachWidgets, widget, value, setValue, setStatus, state, makeLayout, drawUI, choiceMenu, customProfileMenu, generate };`, context);
  const f = context.frontend;
  class Node {
    constructor() {
      this.widgets = Array.from(f.WIDGET_NAMES, (name) => ({ name, value: "", type: "text" }));
      this.inputs = [];
      this.size = [460, 450];
      this.properties = {};
      this.dirty = 0;
      f.detachWidgets(this);
      f.setValue(this, "idea", "A quiet street");
      f.setValue(this, "mode", "Enhance");
      f.setValue(this, "generated_prompt", "existing", false);
    }
    setDirtyCanvas() { this.dirty++; }
    serialize() { return {}; }
  }
  extension.beforeRegisterNodeDef(Node, { name: "GoatedPrompter" });
  const node = new Node();
  const finish = (prompt = "preview") => requests[0].resolve({ ok: true, json: async () => ({ ok: true, prompt }) });
  return { f, node, requests, finish, select: (value) => select(value) };
}

test("canvas reference selector exposes every backend image slot", () => {
  const { f } = fixture();
  assert.deepEqual(Array.from(f.REFERENCE_SOURCES), [
    "Auto", "Image 1", "Image 2", "Blend", "Off", "Image 3", "Image 4",
  ]);
});

test("display status cannot release generation ownership; finally permits retry", async () => {
  const { f, node, requests, finish } = fixture();
  const pending = f.generate(node);
  for (const kind of ["idle", "success", "error"]) {
    f.setStatus(node, kind, "Other feedback");
    await f.generate(node);
    assert.equal(requests.length, 1);
  }
  finish();
  await pending;
  assert.equal(node._goatedPrompterInFlight, false);
  assert.equal(f.value(node, "generated_prompt"), "preview");
  const retry = f.generate(node);
  requests[1].reject(new Error("offline"));
  await retry;
  assert.equal(node._goatedPrompterInFlight, false);
  assert.equal(node._goatedPrompterStatus.message, "offline");
});

const changes = {
  settings: (f, node) => f.setValue(node, "idea", "Changed"),
  "settings changed back": (f, node) => {
    f.setValue(node, "idea", "Changed", false);
    f.setValue(node, "idea", "A quiet street", false);
  },
  "manual output": (f, node) => f.setValue(node, "generated_prompt", "manual", false),
  lock: (f, node) => f.setValue(node, "lock_generated_prompt", true),
  "direct widget write": (f, node) => { f.widget(node, "idea").value = "external"; },
  "workflow result": (_, node) => node.onExecuted({ generated_prompt: ["workflow"] }),
  "identical workflow result": (_, node) => node.onExecuted({ generated_prompt: ["existing"] }),
  configuration: (f, node) => node.onConfigure({ widgets_values: Array.from(f.WIDGET_NAMES, (name) => f.value(node, name)) }),
  connection: (_, node) => node.onConnectionsChange(),
};
for (const [name, change] of Object.entries(changes)) {
  for (const fails of [false, true]) {
    test(`stale ${fails ? "error" : "completion"} preserves ${name}`, async () => {
      const { f, node, requests, finish } = fixture();
      const pending = f.generate(node);
      change(f, node);
      const output = f.value(node, "generated_prompt");
      f.setStatus(node, "idle", "Newer status");
      const status = node._goatedPrompterStatus;
      if (fails) requests[0].reject(new Error("stale failure"));
      else finish();
      await pending;
      assert.equal(f.value(node, "generated_prompt"), output);
      assert.equal(node._goatedPrompterStatus, status);
      assert.equal(node._goatedPrompterInFlight, false);
    });
  }
}

test("unchanged values and combo selections preserve output, revision and working copy", async () => {
  const { f, node, select, finish } = fixture();
  f.setValue(node, "system_prompt_override", "Working copy", false);
  const pending = f.generate(node);
  const revision = node._goatedPrompterRevision;
  const dirty = node.dirty;
  assert.equal(f.setValue(node, "idea", "A quiet street"), false);
  for (const field of ["mode", "director_preset"]) {
    f.choiceMenu(node, field, [f.value(node, field)], {}, () => assert.fail("unchanged afterSelect"));
    select(f.value(node, field));
  }
  assert.equal(node._goatedPrompterRevision, revision);
  assert.equal(node.dirty, dirty);
  assert.equal(f.value(node, "generated_prompt"), "existing");
  assert.equal(f.value(node, "system_prompt_override"), "Working copy");
  finish();
  await pending;
  assert.equal(f.value(node, "generated_prompt"), "preview");
});

test("mode changes preserve the Director and edited behavior; Director changes preserve mode", () => {
  const { f, node, select } = fixture();
  f.setValue(node, "director_preset", "general_director", false);
  f.setValue(node, "system_prompt_override", "Working copy", false);
  node._goatedPrompterHits = [{ kind: "choice", field: "mode", x: 0, y: 0, w: 10, h: 10 }];
  assert.equal(node.onMouseDown({}, [5, 5]), true);
  select("Photography");
  assert.equal(f.value(node, "mode"), "Photography");
  assert.equal(f.value(node, "director_preset"), "general_director");
  assert.equal(f.value(node, "system_prompt_override"), "Working copy");
  assert.equal(f.value(node, "generated_prompt"), "");

  node._goatedPrompterHits[0].field = "director_preset";
  node.onMouseDown({}, [5, 5]);
  select("general_director");
  assert.equal(f.value(node, "system_prompt_override"), "Working copy");
  node.onMouseDown({}, [5, 5]);
  select("custom_director");
  assert.equal(f.value(node, "director_preset"), "custom_director");
  assert.equal(f.value(node, "mode"), "Photography");
  assert.equal(f.value(node, "system_prompt_override"), "");
});

test("configuration retains live converted widgets and serialization; paint does not re-hide", () => {
  const { f, node } = fixture();
  const old = f.widget(node, "idea");
  const computeSize = () => [0, -4];
  const draw = () => {};
  const serializeValue = () => "converted";
  const converted = { name: "idea", value: "converted", type: "converted-widget", computeSize, draw, serializeValue };
  node.widgets[node.widgets.indexOf(old)] = converted;
  const values = Array.from(f.WIDGET_NAMES, (name) => f.value(node, name));
  values[0] = "configured";
  node.onConfigure({ widgets_values: values });
  assert.equal(f.widget(node, "idea"), converted);
  assert.equal(converted.computeSize, computeSize);
  assert.equal(converted.draw, draw);
  assert.equal(converted.serializeValue, serializeValue);
  assert.equal(node.serialize().widgets_values[0], "configured");
  const regular = f.widget(node, "mode");
  regular.computeSize = computeSize;
  const map = node._goatedPrompterWidgetMap;
  node.size = [300, f.makeLayout(node).desiredHeight];
  const ctx = { measureText: (text) => ({ width: text.length * 6 }), beginPath() {}, arc() {}, fill() {} };
  node.onDrawForeground(ctx);
  node.onDrawForeground(ctx);
  assert.equal(node.size[0], 400);
  assert.equal(node._goatedPrompterWidgetMap, map);
  assert.equal(regular.computeSize, computeSize);
  assert.equal(converted.computeSize, computeSize);
});

test("generation stays owned through response parsing and discards changes during parsing", async () => {
  const { f, node, requests } = fixture();
  let finishBody;
  const body = new Promise((resolve) => { finishBody = resolve; });
  const pending = f.generate(node);
  requests[0].resolve({ ok: true, json: () => body });
  await Promise.resolve();
  f.setValue(node, "lock_generated_prompt", true);
  await f.generate(node);
  assert.equal(requests.length, 1);
  assert.equal(node._goatedPrompterInFlight, true);
  finishBody({ ok: true, prompt: "stale" });
  await pending;
  assert.equal(f.value(node, "generated_prompt"), "existing");
  assert.equal(node._goatedPrompterInFlight, false);
  assert.equal(node._goatedPrompterStatus.kind, "idle");
});

test("unchanged custom profile keeps explicit paths and generated output", () => {
  const { f, node, select } = fixture();
  node._goatedPrompterDiscovery = { profiles: [{ id: "local", label: "Local", vision_ready: true }] };
  f.setValue(node, "director_profile", "local", false);
  f.setValue(node, "director_model_path", "model.gguf", false);
  f.setValue(node, "director_mmproj_path", "mmproj.gguf", false);
  f.customProfileMenu(node, {});
  select("Local");
  assert.equal(f.value(node, "director_model_path"), "model.gguf");
  assert.equal(f.value(node, "director_mmproj_path"), "mmproj.gguf");
  assert.equal(f.value(node, "generated_prompt"), "existing");
});

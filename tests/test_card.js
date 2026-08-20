/**
 * Tests for plant-card, the bundled Lovelace card.
 *
 * Run with: node tests/test_card.js
 *
 * The card is a plain custom element, so it runs under a small stub of the
 * few browser globals it touches. No DOM library, no build step.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const CARD = path.join(
  __dirname,
  "..",
  "custom_components",
  "plant_care",
  "www",
  "plant-card.js"
);
const src = fs.readFileSync(CARD, "utf8");

let passed = 0;
function ok(message) {
  passed += 1;
  console.log(`  ok ${message}`);
}
function section(name) {
  console.log(`\n${name}`);
}

function makeRegistry(seed = []) {
  const defined = new Map(seed.map((name) => [name, class {}]));
  return {
    defined,
    define(name, cls) {
      if (defined.has(name)) {
        throw new Error(
          `Failed to execute 'define': the name "${name}" has already been used with this registry`
        );
      }
      defined.set(name, cls);
    },
    get(name) {
      return defined.get(name);
    },
  };
}

/**
 * Loads the card into a stub of the browser globals it touches.
 *
 * `window` is the context itself, so `window.customElements` and the bare
 * `HTMLElement` global are the same objects the module sees in a browser —
 * which is what lets us simulate app.js swapping them mid-boot.
 */
function load({ frontendReady = true } = {}) {
  const registry = makeRegistry(frontendReady ? ["home-assistant"] : []);
  const ctx = {
    console: { info() {} },
    HTMLElement: class {
      appendChild() {}
    },
    customElements: registry,
    document: {
      createElement: (tag) => ({
        _tag: tag,
        _listeners: {},
        addEventListener(type, fn) {
          (this._listeners[type] = this._listeners[type] || []).push(fn);
        },
        appendChild() {},
        setAttribute() {},
      }),
    },
    CustomEvent: class {
      constructor(type, opts = {}) {
        this.type = type;
        this.detail = opts.detail;
      }
    },
    Intl,
    Date,
    Number,
    Object,
    Math,
    Boolean,
    String,
    setInterval,
    clearInterval,
    setTimeout,
    clearTimeout,
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(
    `${src}\n;this.__t = { buildClasses, EDITOR_SCHEMA, EDITOR_LABELS, pruneConfig, stampOf, isoStamp, statusOf, daysSince, register, PICKER_ENTRY };`,
    ctx
  );

  // Classes are exposed through getters, so tests that never touch them leave
  // them unbuilt — which is what the lazy-binding test below depends on.
  const api = { ...ctx.__t, window: ctx, ctx, registry };
  for (const name of ["PlantCard", "PlantCardEditor"]) {
    Object.defineProperty(api, name, {
      get: () => ctx.__t.buildClasses()[name],
    });
  }
  return api;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const daysAgoIso = (days) =>
  new Date(Date.now() - days * 86400 * 1000).toISOString();

/* ------------------------------------------------------------------ *
 * getStubConfig must never throw.
 *
 * Home Assistant awaits it while building the card picker and does not
 * wrap the call. Anything thrown rejects the picker's render promise,
 * and the card's tile spins forever instead of appearing.
 * ------------------------------------------------------------------ */
section("getStubConfig is total");
{
  const { PlantCard } = load();
  const hostile = [
    ["undefined hass", undefined],
    ["null hass", null],
    ["hass without states", {}],
    ["states null", { states: null }],
    ["entity without attributes", { states: { "sensor.a": {} } }],
    ["attributes null", { states: { "sensor.a": { attributes: null } } }],
    ["null state object", { states: { "sensor.a": null } }],
    ["no sensors at all", { states: { "light.a": { attributes: {} } } }],
  ];
  for (const [label, hass] of hostile) {
    let stub;
    assert.doesNotThrow(() => {
      stub = PlantCard.getStubConfig(hass);
    }, `threw on ${label}`);
    assert.equal(stub.type, "custom:plant-card");
    assert.ok(stub.entity || stub.last_watered, `unusable stub for ${label}`);
    ok(`survives ${label}`);
  }

  const hass = {
    states: {
      "sensor.other": { attributes: {} },
      "sensor.monstera_plant": {
        attributes: { last_watered_entity: "datetime.m" },
      },
    },
  };
  assert.deepEqual(PlantCard.getStubConfig(hass), {
    type: "custom:plant-card",
    entity: "sensor.monstera_plant",
  });
  ok("prefers a Plant Care summary entity");

  assert.doesNotThrow(() => PlantCard.getStubConfig(hass, ["a"], ["b"]));
  ok("accepts HA's (hass, entities, entitiesFallback) signature");
}

/* ------------------------------------------------------------------ */
section("picker registration");
{
  const { window: win, registry } = load();
  const entry = win.customCards.find((c) => c.type === "plant-card");
  assert.ok(entry, "not registered in window.customCards");
  assert.equal(entry.name, "Plant Card");
  ok(`registered as "${entry.name}"`);
  assert.ok(registry.get("plant-card") && registry.get("plant-card-editor"));
  ok("both custom elements defined");
}

section("loading the module twice");
{
  const { ctx, window: win } = load();
  // Each real load is its own module scope but shares globals.
  assert.doesNotThrow(() => {
    vm.runInContext(`(function(){${src}\n})()`, ctx);
  }, "second load threw");
  assert.equal(win.customCards.filter((c) => c.type === "plant-card").length, 1);
  ok("no throw and no duplicate picker entry");
}

/* ------------------------------------------------------------------ */
section("config resolution");
{
  const { PlantCard } = load();
  const hass = {
    locale: { language: "en" },
    states: {
      "sensor.monstera_plant": {
        state: "needs_fertilizer",
        attributes: {
          plant_name: "Monstera",
          last_watered: daysAgoIso(5),
          last_fertilized: daysAgoIso(34),
          last_watered_entity: "datetime.monstera_last_watered",
          last_fertilized_entity: "datetime.monstera_last_fertilized",
          water_interval: 7,
          fertilize_interval: 30,
          temperature_entity: "sensor.t",
          humidity_entity: "sensor.h",
          illuminance_entity: "sensor.l",
          moisture_entity: null,
        },
      },
    },
  };
  const make = (config) => {
    const card = Object.create(PlantCard.prototype);
    card.setConfig(config);
    card._hass = hass;
    return card;
  };

  let card = make({ entity: "sensor.monstera_plant" });
  let resolved = card._resolve();
  assert.equal(resolved.name, "Monstera");
  assert.equal(resolved.last_watered, "datetime.monstera_last_watered");
  assert.equal(resolved.fertilize_interval, 30);
  assert.ok(!resolved.moisture, "null attribute must not become a sensor");
  assert.deepEqual(
    card._sensorEntities(resolved).map((s) => s.key),
    ["temperature", "humidity", "illuminance"]
  );
  ok("summary entity supplies name, entities and intervals");

  card = make({ entity: "sensor.monstera_plant", name: "Big", water_interval: 3 });
  resolved = card._resolve();
  assert.equal(resolved.name, "Big");
  assert.equal(resolved.water_interval, 3);
  assert.equal(resolved.fertilize_interval, 30);
  ok("explicit YAML overrides the summary entity");

  card = make({ last_watered: "input_datetime.x" });
  resolved = card._resolve();
  assert.equal(resolved.name, "Plant");
  assert.equal(card._hubStamps, null);
  ok("legacy input_datetime config untouched");

  assert.throws(() => make({}), /entity.*last_watered/is);
  ok("empty config rejected");
}

/* ------------------------------------------------------------------ */
section("logging routes to the right service");
{
  const { PlantCard } = load();
  for (const [entity, expected] of [
    ["datetime.x", ["datetime", "set_value"]],
    ["input_datetime.y", ["input_datetime", "set_datetime"]],
  ]) {
    const calls = [];
    const card = Object.create(PlantCard.prototype);
    card.setConfig({ last_watered: entity });
    card._hass = { states: {}, callService: (d, s, data) => calls.push([d, s, data]) };
    card._log("water", entity);
    assert.deepEqual(calls[0].slice(0, 2), expected);
    assert.ok(calls[0][2].entity_id === entity);
    ok(`${entity} -> ${expected.join(".")}`);
  }
}

/* ------------------------------------------------------------------ */
section("visual editor");
{
  const { PlantCard, PlantCardEditor, EDITOR_SCHEMA, EDITOR_LABELS, pruneConfig } =
    load();

  assert.equal(PlantCard.getConfigElement()._tag, "plant-card-editor");
  ok("getConfigElement returns the editor element");

  const leaves = [];
  (function walk(schema) {
    for (const item of schema) {
      assert.ok("name" in item, "schema entry without a name");
      if (item.schema) {
        assert.ok(item.type, "nested section without a type");
        walk(item.schema);
      } else {
        assert.ok(item.selector, `leaf ${item.name} has no selector`);
        leaves.push(item.name);
      }
    }
  })(EDITOR_SCHEMA);
  const unlabelled = leaves.filter((n) => !EDITOR_LABELS[n]);
  assert.deepEqual(unlabelled, [], `unlabelled fields: ${unlabelled}`);
  ok(`${leaves.length} fields, each with a selector and a label`);

  assert.deepEqual(
    pruneConfig({ entity: "sensor.p", name: "", icon: null, confirm: false, water_interval: 0 }),
    { type: "custom:plant-card", entity: "sensor.p", confirm: false, water_interval: 0 }
  );
  ok("pruneConfig keeps false and 0, drops blanks");

  const editor = Object.create(PlantCardEditor.prototype);
  const events = [];
  editor.appendChild = () => {};
  editor.dispatchEvent = (event) => events.push(event);
  editor.setConfig({ type: "custom:plant-card", entity: "sensor.p" });
  editor.hass = { states: {} };
  assert.ok(editor._form, "ha-form was not created");
  editor._form._listeners["value-changed"][0]({
    stopPropagation() {},
    detail: { value: { entity: "sensor.q", name: "" } },
  });
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "config-changed");
  assert.deepEqual(events[0].detail.config, {
    type: "custom:plant-card",
    entity: "sensor.q",
  });
  ok("editor emits config-changed with the type preserved");
}

/* ------------------------------------------------------------------ */
section("time helpers");
{
  const { stampOf, isoStamp, daysSince, statusOf } = load();
  assert.equal(stampOf(null), null);
  assert.equal(stampOf({ state: "unavailable", attributes: {} }), null);
  assert.ok(
    Math.abs(daysSince(stampOf({ state: daysAgoIso(3), attributes: {} })) - 3) < 0.01
  );
  ok("ISO timestamp sensors parse");
  const stamp = Date.now() / 1000 - 2 * 86400;
  assert.ok(
    Math.abs(
      daysSince(stampOf({ state: "x", attributes: { timestamp: stamp, has_date: true } })) - 2
    ) < 0.01
  );
  ok("input_datetime timestamp attribute parses");
  assert.ok(Math.abs(daysSince(isoStamp(daysAgoIso(9))) - 9) < 0.01);
  ok("raw ISO fallback parses");
  assert.equal(statusOf(null, 7), "overdue");
  assert.equal(statusOf(1, 7), "ok");
  assert.equal(statusOf(6.9, 7), "soon");
  assert.equal(statusOf(7, 7), "overdue");
  ok("status thresholds: never=overdue, 1d=ok, 6.9d=soon, 7d=overdue");
}

/* ------------------------------------------------------------------ */
section("care details panel");
{
  const { PlantCard } = load();
  const iso = (days) =>
    new Date(Date.now() - days * 86400 * 1000).toISOString();
  const future = (days) =>
    new Date(Date.now() + days * 86400 * 1000).toISOString();

  const hass = {
    locale: { language: "en" },
    states: {
      "sensor.monstera_plant": {
        state: "ok",
        attributes: {
          plant_name: "Monstera",
          last_watered: iso(2),
          last_fertilized: iso(9),
          last_watered_entity: "datetime.monstera_last_watered",
          last_fertilized_entity: "datetime.monstera_last_fertilized",
          water_interval: 7,
          fertilize_interval: 30,
          next_water_due: future(5),
          next_fertilize_due: future(21),
          watering_history: [iso(2), iso(9), iso(16), iso(23)],
          fertilizing_history: [iso(9)],
        },
      },
      "datetime.monstera_last_watered": { state: iso(2), attributes: {} },
      "datetime.monstera_last_fertilized": { state: iso(9), attributes: {} },
    },
  };

  const build = (config) => {
    const card = Object.create(PlantCard.prototype);
    card.setConfig({ entity: "sensor.monstera_plant", ...config });
    card._hass = hass;
    card._config = card._resolve();
    return card;
  };

  const waterItem = {
    kind: "water",
    entity: "datetime.monstera_last_watered",
    interval: 7,
    label: "Watered",
  };

  let card = build({ history_length: 3 });
  let html = card._careDetailHtml(waterItem, "en");

  assert.ok(html.includes("<dt>Last</dt>"), "no Last row");
  assert.ok(html.includes("<dt>Next due</dt>"), "no Next due row");
  assert.ok(html.includes("<dd>7 days</dd>"), "interval missing");
  ok("shows last, next due and interval");

  assert.ok(/in 5 days/.test(html), `next due should read as future: ${html}`);
  ok("next due reads as a future date");

  const late = Object.create(PlantCard.prototype);
  late.setConfig({ last_watered: "input_datetime.late" });
  late._hass = {
    locale: { language: "en" },
    states: { "input_datetime.late": { state: iso(10), attributes: {} } },
  };
  late._config = late._resolve();
  const overdue = late._careDetailHtml(
    { kind: "water", entity: "input_datetime.late", interval: 7, label: "Watered" },
    "en"
  );
  assert.ok(overdue.includes("overdue"), `past due should say overdue: ${overdue}`);
  assert.ok(!/ago<\/dd>/.test(overdue), "past due should not read as 'x ago'");
  ok("a past due date reads as overdue, not '3 days ago'");

  assert.ok(html.includes("Recent"), "no history section");
  assert.equal((html.match(/<li>/g) || []).length, 3, "history_length ignored");
  ok("lists history, capped by history_length");

  assert.ok(
    html.includes('data-more-info="datetime.monstera_last_watered"'),
    "no more-info affordance"
  );
  ok("offers a link to the underlying entity");

  // A single event says nothing the Last row does not.
  const fertilizeItem = {
    kind: "fertilize",
    entity: "datetime.monstera_last_fertilized",
    interval: 30,
    label: "Fertilized",
  };
  html = card._careDetailHtml(fertilizeItem, "en");
  assert.ok(!html.includes("Recent"), "single-entry history should be hidden");
  ok("hides the log when there is only one event");

  // Without a summary entity there is no history, but dates still work.
  const plain = Object.create(PlantCard.prototype);
  plain.setConfig({ last_watered: "input_datetime.x" });
  plain._hass = {
    locale: { language: "en" },
    states: { "input_datetime.x": { state: iso(3), attributes: {} } },
  };
  plain._config = plain._resolve();
  html = plain._careDetailHtml(
    { kind: "water", entity: "input_datetime.x", interval: 7, label: "Watered" },
    "en"
  );
  assert.ok(html.includes("<dt>Next due</dt>"), "next due must be computed");
  assert.ok(!html.includes("Recent"), "no history without a summary entity");
  ok("degrades gracefully for input_datetime setups");

  // Never logged.
  const fresh = Object.create(PlantCard.prototype);
  fresh.setConfig({ last_watered: "input_datetime.x" });
  fresh._hass = { locale: { language: "en" }, states: {} };
  fresh._config = fresh._resolve();
  html = fresh._careDetailHtml(
    { kind: "water", entity: "input_datetime.x", interval: 7, label: "Watered" },
    "en"
  );
  assert.ok(html.includes("never"), "should say never");
  assert.ok(html.includes("<dd>—</dd>"), "next due should be unknown");
  ok("handles a plant that was never watered");

  // Entity ids land in an HTML attribute.
  const { PlantCard: PC } = load();
  const hostile = Object.create(PC.prototype);
  hostile.setConfig({ last_watered: 'input_datetime.x"><img src=x onerror=1>' });
  hostile._hass = { locale: { language: "en" }, states: {} };
  hostile._config = hostile._resolve();
  html = hostile._careDetailHtml(
    {
      kind: "water",
      entity: 'input_datetime.x"><img src=x onerror=1>',
      interval: 7,
      label: "Watered",
    },
    "en"
  );
  assert.ok(!html.includes("<img"), "entity id was not escaped");
  ok("escapes entity ids before interpolating them");
}

/* ------------------------------------------------------------------ *
 * Regression: "Custom element not found: plant-card"
 *
 * index.html imports this module in parallel with app.js. app.js installs
 * the scoped-custom-element-registry polyfill, which REPLACES
 * window.customElements and window.HTMLElement outright — no fallback to
 * the native registry. Being far smaller than app.js, this module normally
 * wins the race, so defining on load put the card in the registry that was
 * about to be thrown away: defined, but invisible to the card picker.
 * ------------------------------------------------------------------ */
(async () => {
  section("registers into the registry Home Assistant ends up with");

  const { ctx, window: win, registry: nativeRegistry } = load({
    frontendReady: false,
  });

  assert.equal(nativeRegistry.get("plant-card"), undefined);
  assert.ok(
    !(win.customCards || []).some((c) => c.type === "plant-card"),
    "picker entry must not appear before the element is defined"
  );
  ok("waits while the frontend is still booting, leaving no orphan tile");

  // Simulate app.js installing the polyfill.
  const patchedHTMLElement = class {
    appendChild() {}
  };
  const haRegistry = makeRegistry(["home-assistant", "ha-card"]);
  ctx.HTMLElement = patchedHTMLElement;
  ctx.customElements = haRegistry;

  await sleep(300);

  const cls = haRegistry.get("plant-card");
  assert.ok(cls, "card never registered after the frontend became ready");
  ok("registers as soon as Home Assistant's own elements appear");

  assert.ok(haRegistry.get("plant-card-editor"), "editor not registered");
  ok("editor registered in the same registry");

  assert.equal(
    nativeRegistry.get("plant-card"),
    undefined,
    "must not define into the registry that gets discarded"
  );
  ok("never touches the discarded native registry");

  assert.equal(
    Object.getPrototypeOf(cls),
    patchedHTMLElement,
    "class was bound to the pre-polyfill HTMLElement"
  );
  ok("class extends the patched HTMLElement, not the original");

  assert.ok(win.customCards.some((c) => c.type === "plant-card"));
  ok("picker entry appears together with the definition");

  assert.doesNotThrow(() => ctx.__t.register(), "register() is not idempotent");
  assert.equal(
    win.customCards.filter((c) => c.type === "plant-card").length,
    1
  );
  ok("register() can be called again safely");

  console.log(`\n${passed} card assertions passed`);
})();

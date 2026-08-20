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

function load() {
  const defined = new Map();
  const ctx = {
    console: { info() {} },
    window: {},
    HTMLElement: class {
      appendChild() {}
    },
    customElements: {
      define(name, cls) {
        if (defined.has(name)) throw new Error(`already defined: ${name}`);
        defined.set(name, cls);
      },
      get(name) {
        return defined.get(name);
      },
    },
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
    setInterval,
    clearInterval,
    setTimeout,
    clearTimeout,
  };
  vm.createContext(ctx);
  vm.runInContext(
    `${src}\n;this.__t = { PlantCard, PlantCardEditor, EDITOR_SCHEMA, EDITOR_LABELS, pruneConfig, stampOf, isoStamp, statusOf, daysSince };`,
    ctx
  );
  return { ...ctx.__t, window: ctx.window, defined, ctx };
}

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
  const { window: win, defined } = load();
  const entry = win.customCards.find((c) => c.type === "plant-card");
  assert.ok(entry, "not registered in window.customCards");
  assert.equal(entry.name, "Plant Card");
  ok(`registered as "${entry.name}"`);
  assert.ok(defined.has("plant-card") && defined.has("plant-card-editor"));
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

console.log(`\n${passed} card assertions passed`);

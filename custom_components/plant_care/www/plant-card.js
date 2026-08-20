/**
 * plant-card — a Lovelace card for tracking plant care.
 *
 * Shows when a plant was last watered and last fertilized (as relative time
 * plus a progress bar towards the next due date), and an optional row of
 * environment sensors (temperature, humidity, illuminance, soil moisture).
 *
 * Two ways to configure it:
 *   entity: sensor.monstera_plant   — a Plant Care summary entity, which
 *                                     carries every other setting already
 *   last_watered: input_datetime.…  — spell each entity out yourself
 *
 * No build step: this file is the distributable. Plain custom element, no
 * framework, so it keeps working across Home Assistant frontend releases.
 */

const CARD_VERSION = "1.2.0";

console.info(
  `%c PLANT-CARD %c ${CARD_VERSION} `,
  "color:#fff;background:#43a047;font-weight:700",
  "color:#43a047;background:#f1f8e9"
);

const UNAVAILABLE = ["unknown", "unavailable", "none", ""];

const DEFAULTS = {
  name: "Plant",
  icon: "mdi:flower",
  water_interval: 7,
  fertilize_interval: 30,
  water_label: "Watered",
  fertilize_label: "Fertilized",
  water_noun: "water",
  fertilize_noun: "fertilizer",
  confirm: true,
  tap_to_log: true,
  show_progress: true,
};

/** Map a Plant Care summary entity's attributes onto card config. */
const HUB_KEYS = {
  name: "plant_name",
  last_watered: "last_watered_entity",
  last_fertilized: "last_fertilized_entity",
  water_interval: "water_interval",
  fertilize_interval: "fertilize_interval",
  temperature: "temperature_entity",
  humidity: "humidity_entity",
  illuminance: "illuminance_entity",
  moisture: "moisture_entity",
};

const SENSOR_ROW = [
  { key: "temperature", icon: "mdi:thermometer" },
  { key: "humidity", icon: "mdi:water-percent" },
  { key: "illuminance", icon: "mdi:white-balance-sunny" },
  { key: "moisture", icon: "mdi:sprout-outline" },
];

/** Unix seconds for an input_datetime / timestamp sensor, or null. */
function stampOf(stateObj) {
  if (!stateObj) return null;
  const state = stateObj.state;
  if (state == null || UNAVAILABLE.includes(String(state).toLowerCase())) return null;

  // input_datetime exposes an absolute unix timestamp when it has date + time.
  const attr = stateObj.attributes || {};
  if (typeof attr.timestamp === "number" && attr.has_date !== false) {
    return attr.timestamp;
  }

  // sensor with device_class: timestamp (ISO 8601), or a plain "Y-m-d H:i:s".
  const parsed = Date.parse(state.includes("T") ? state : state.replace(" ", "T"));
  return Number.isNaN(parsed) ? null : parsed / 1000;
}

/** Unix seconds from a bare ISO string. */
function isoStamp(iso) {
  if (!iso) return null;
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? null : parsed / 1000;
}

function daysSince(stamp) {
  if (stamp == null) return null;
  return (Date.now() / 1000 - stamp) / 86400;
}

/** "2 days ago" / "yesterday", localized to the user's HA language. */
function relativeTime(stamp, language) {
  if (stamp == null) return "never";
  const seconds = Date.now() / 1000 - stamp;
  let fmt;
  try {
    fmt = new Intl.RelativeTimeFormat(language || "en", { numeric: "auto" });
  } catch (_e) {
    fmt = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  }
  const abs = Math.abs(seconds);
  if (abs < 90) return fmt.format(-Math.round(seconds / 60), "minute");
  if (abs < 3600 * 22) return fmt.format(-Math.round(seconds / 3600), "hour");
  if (abs < 86400 * 30) return fmt.format(-Math.round(seconds / 86400), "day");
  if (abs < 86400 * 365) return fmt.format(-Math.round(seconds / (86400 * 30)), "month");
  return fmt.format(-Math.round(seconds / (86400 * 365)), "year");
}

function statusOf(elapsedDays, intervalDays) {
  if (elapsedDays == null) return "overdue";
  if (!intervalDays) return "ok";
  const ratio = elapsedDays / intervalDays;
  if (ratio >= 1) return "overdue";
  if (ratio >= 0.8) return "soon";
  return "ok";
}

function fireEvent(node, type, detail = {}) {
  node.dispatchEvent(
    new CustomEvent(type, { detail, bubbles: true, composed: true })
  );
}

class PlantCard extends HTMLElement {
  /** Gives the card a visual editor in the "Add card" dialog. */
  static getConfigElement() {
    return document.createElement("plant-card-editor");
  }

  static getStubConfig(hass) {
    const summary = Object.keys(hass ? hass.states : {}).find(
      (id) => id.startsWith("sensor.") && hass.states[id].attributes.last_watered_entity
    );
    if (summary) return { type: "custom:plant-card", entity: summary };
    return {
      type: "custom:plant-card",
      name: "Plant",
      last_watered: "input_datetime.plant_last_watered",
      last_fertilized: "input_datetime.plant_last_fertilized",
    };
  }

  setConfig(config) {
    if (!config || (!config.entity && !config.last_watered)) {
      throw new Error(
        "plant-card: set `entity` to a Plant Care plant sensor, or `last_watered` to a datetime entity"
      );
    }
    // Kept raw: defaults are applied after the summary entity is read, so a
    // value from the integration still beats a default but never beats YAML.
    this._userConfig = { ...config };
    this._config = { ...DEFAULTS, ...config };
    // Force a rebuild so a config change can never leave stale nodes behind.
    this._built = false;
    this._armed = null;
    if (this._hass) this._update();
  }

  /** Merge defaults, the summary entity's attributes, and explicit YAML. */
  _resolve() {
    const user = this._userConfig;
    const fromHub = {};

    if (user.entity) {
      const stateObj = this._hass.states[user.entity];
      const attrs = (stateObj && stateObj.attributes) || {};
      for (const [key, attr] of Object.entries(HUB_KEYS)) {
        if (attrs[attr] !== undefined && attrs[attr] !== null) {
          fromHub[key] = attrs[attr];
        }
      }
      // Fall back to the raw timestamps if the datetime entities are hidden
      // or not registered yet.
      this._hubStamps = {
        water: attrs.last_watered || null,
        fertilize: attrs.last_fertilized || null,
      };
    } else {
      this._hubStamps = null;
    }

    return { ...DEFAULTS, ...fromHub, ...user };
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    return this._config && this._sensorEntities().length ? 3 : 2;
  }

  _sensorEntities(config) {
    const cfg = config || this._config;
    if (!cfg) return [];
    return SENSOR_ROW.filter((s) => cfg[s.key]).map((s) => ({
      ...s,
      entity: cfg[s.key],
    }));
  }

  _update() {
    if (!this._hass || !this._userConfig) return;

    const resolved = this._resolve();
    this._config = resolved;

    // The summary entity can gain or lose sensors while the card is live, so
    // rebuild when the sensor row's shape actually changes.
    const key = this._sensorEntities(resolved)
      .map((s) => s.entity)
      .join(",");
    if (!this._built || key !== this._sensorKey) {
      this._sensorKey = key;
      this._build();
    }
    this._paint();
  }

  _build() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const cfg = this._config;
    const sensors = this._sensorEntities();

    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }
        .header {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .avatar {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--plant-accent-bg, rgba(67, 160, 71, 0.14));
          color: var(--plant-accent, #43a047);
          flex: 0 0 auto;
          overflow: hidden;
        }
        .avatar img { width: 100%; height: 100%; object-fit: cover; }
        .title {
          font-size: 1.15rem;
          font-weight: 500;
          color: var(--primary-text-color);
          line-height: 1.2;
        }
        .subtitle {
          font-size: 0.8rem;
          color: var(--secondary-text-color);
        }
        .care { display: flex; flex-direction: column; gap: 10px; }
        .row {
          display: grid;
          grid-template-columns: 24px 1fr auto;
          align-items: center;
          gap: 12px;
          padding: 6px 8px;
          margin: -6px -8px;
          border-radius: 10px;
          --status-color: var(--secondary-text-color);
        }
        .row.tappable { cursor: pointer; }
        .row.tappable:hover { background: var(--secondary-background-color); }
        .row.armed { background: var(--secondary-background-color); }
        .row.ok { --status-color: var(--success-color, #43a047); }
        .row.soon { --status-color: var(--warning-color, #ffa726); }
        .row.overdue { --status-color: var(--error-color, #e53935); }
        .row ha-icon { color: var(--status-color); --mdc-icon-size: 22px; }
        .label {
          font-size: 0.95rem;
          color: var(--primary-text-color);
        }
        .value {
          font-size: 0.95rem;
          font-weight: 500;
          color: var(--status-color);
          text-align: right;
          white-space: nowrap;
        }
        .bar {
          grid-column: 2 / 4;
          height: 4px;
          border-radius: 2px;
          background: var(--divider-color);
          overflow: hidden;
        }
        .bar > div {
          height: 100%;
          background: var(--status-color);
          border-radius: 2px;
          transition: width 0.3s ease;
        }
        .sensors {
          display: flex;
          flex-wrap: wrap;
          gap: 8px 18px;
          padding-top: 12px;
          border-top: 1px solid var(--divider-color);
        }
        .sensor {
          display: flex;
          align-items: center;
          gap: 6px;
          cursor: pointer;
          font-size: 0.9rem;
          color: var(--primary-text-color);
        }
        .sensor ha-icon {
          --mdc-icon-size: 18px;
          color: var(--state-icon-color, var(--secondary-text-color));
        }
        .sensor.stale { opacity: 0.45; }
      </style>
      <ha-card>
        <div class="header">
          <div class="avatar" id="avatar"><ha-icon id="icon"></ha-icon></div>
          <div>
            <div class="title" id="title"></div>
            <div class="subtitle" id="subtitle"></div>
          </div>
        </div>
        <div class="care">
          <div class="row" id="row-water">
            <ha-icon icon="mdi:watering-can"></ha-icon>
            <div class="label" id="label-water"></div>
            <div class="value" id="value-water"></div>
            <div class="bar" id="bar-water"><div></div></div>
          </div>
          <div class="row" id="row-fertilize">
            <ha-icon icon="mdi:leaf"></ha-icon>
            <div class="label" id="label-fertilize"></div>
            <div class="value" id="value-fertilize"></div>
            <div class="bar" id="bar-fertilize"><div></div></div>
          </div>
        </div>
        ${sensors.length ? `<div class="sensors" id="sensors"></div>` : ""}
      </ha-card>
    `;

    const $ = (id) => this.shadowRoot.getElementById(id);
    this._el = {
      icon: $("icon"),
      avatar: $("avatar"),
      title: $("title"),
      subtitle: $("subtitle"),
      rows: {
        water: {
          row: $("row-water"),
          label: $("label-water"),
          value: $("value-water"),
          bar: $("bar-water"),
        },
        fertilize: {
          row: $("row-fertilize"),
          label: $("label-fertilize"),
          value: $("value-fertilize"),
          bar: $("bar-fertilize"),
        },
      },
      sensors: $("sensors"),
    };

    if (!cfg.last_fertilized && !(this._hubStamps && this._hubStamps.fertilize)) {
      this._el.rows.fertilize.row.style.display = "none";
    }

    for (const kind of ["water", "fertilize"]) {
      const { row } = this._el.rows[kind];
      if (cfg.tap_to_log) {
        row.classList.add("tappable");
        row.addEventListener("click", () => this._onCareTap(kind));
      }
    }

    if (sensors.length) {
      this._el.sensorNodes = sensors.map((s) => {
        const node = document.createElement("div");
        node.className = "sensor";
        node.innerHTML = `<ha-icon icon="${s.icon}"></ha-icon><span></span>`;
        node.addEventListener("click", () =>
          fireEvent(this, "hass-more-info", { entityId: s.entity })
        );
        this._el.sensors.appendChild(node);
        return { ...s, node, text: node.querySelector("span") };
      });
    }

    this._built = true;
    this._startTicker();
  }

  /** Relative times drift; repaint every 30 s even without a state change. */
  _startTicker() {
    if (this._ticker) clearInterval(this._ticker);
    this._ticker = setInterval(() => this._hass && this._paint(), 30000);
  }

  disconnectedCallback() {
    if (this._ticker) clearInterval(this._ticker);
    this._ticker = null;
    if (this._disarmTimer) clearTimeout(this._disarmTimer);
  }

  connectedCallback() {
    if (this._built && !this._ticker) this._startTicker();
  }

  _paint() {
    const cfg = this._config;
    const hass = this._hass;
    const lang = (hass.locale && hass.locale.language) || hass.language;

    this._el.title.textContent = cfg.name;
    if (cfg.image) {
      // Only swap once — rebuilding the <img> on every repaint would flicker.
      if (!this._el.avatar.querySelector("img")) {
        this._el.avatar.innerHTML = `<img src="${cfg.image}" alt="">`;
      }
    } else {
      this._el.icon.setAttribute("icon", cfg.icon);
    }

    const care = [
      {
        kind: "water",
        entity: cfg.last_watered,
        interval: cfg.water_interval,
        label: cfg.water_label,
        noun: cfg.water_noun,
      },
      {
        kind: "fertilize",
        entity: cfg.last_fertilized,
        interval: cfg.fertilize_interval,
        label: cfg.fertilize_label,
        noun: cfg.fertilize_noun,
      },
    ];

    const overdue = [];

    for (const item of care) {
      const el = this._el.rows[item.kind];
      const fallbackIso = this._hubStamps ? this._hubStamps[item.kind] : null;
      if (!item.entity && !fallbackIso) continue;

      const stateObj = item.entity ? hass.states[item.entity] : undefined;
      const stamp = stampOf(stateObj) ?? isoStamp(fallbackIso);
      const elapsed = daysSince(stamp);
      const status = statusOf(elapsed, item.interval);

      el.row.classList.remove("ok", "soon", "overdue");
      el.row.classList.add(status);

      if (item.entity && !stateObj && !fallbackIso) {
        el.label.textContent = item.label;
        el.value.textContent = "entity not found";
        el.bar.style.display = "none";
        continue;
      }

      el.label.textContent =
        this._armed === item.kind ? "Tap again to confirm" : item.label;
      el.value.textContent = relativeTime(stamp, lang);

      if (cfg.show_progress && item.interval) {
        el.bar.style.display = "";
        const pct = elapsed == null ? 100 : Math.min(100, (elapsed / item.interval) * 100);
        el.bar.firstElementChild.style.width = `${pct}%`;
      } else {
        el.bar.style.display = "none";
      }

      if (status === "overdue") overdue.push(item.noun);
    }

    this._el.subtitle.textContent = overdue.length
      ? `Needs ${overdue.join(" & ")}`
      : "All good";

    if (this._el.sensorNodes) {
      for (const s of this._el.sensorNodes) {
        const stateObj = hass.states[s.entity];
        const missing =
          !stateObj || UNAVAILABLE.includes(String(stateObj.state).toLowerCase());
        s.node.classList.toggle("stale", missing);
        s.text.textContent = missing ? "—" : this._formatState(stateObj);
      }
    }
  }

  _formatState(stateObj) {
    const hass = this._hass;
    if (typeof hass.formatEntityState === "function") {
      try {
        return hass.formatEntityState(stateObj);
      } catch (_e) {
        /* fall through to the manual format */
      }
    }
    const unit = stateObj.attributes.unit_of_measurement;
    return unit ? `${stateObj.state} ${unit}` : stateObj.state;
  }

  _onCareTap(kind) {
    const cfg = this._config;
    const entity = kind === "water" ? cfg.last_watered : cfg.last_fertilized;
    if (!entity) return;

    if (cfg.confirm && this._armed !== kind) {
      this._armed = kind;
      fireEvent(this, "haptic", "light");
      if (this._disarmTimer) clearTimeout(this._disarmTimer);
      this._disarmTimer = setTimeout(() => {
        this._armed = null;
        this._paint();
      }, 4000);
      this._paint();
      return;
    }

    this._armed = null;
    if (this._disarmTimer) clearTimeout(this._disarmTimer);
    this._log(kind, entity);
    fireEvent(this, "haptic", "success");
    this._paint();
  }

  _log(kind, entity) {
    const cfg = this._config;
    const script = kind === "water" ? cfg.water_script : cfg.fertilize_script;

    if (script) {
      const [domain, service] = script.split(".");
      this._hass.callService(domain, service, {});
      return;
    }

    if (entity.startsWith("datetime.")) {
      this._hass.callService("datetime", "set_value", {
        entity_id: entity,
        datetime: new Date().toISOString(),
      });
      return;
    }

    if (entity.startsWith("input_datetime.")) {
      this._hass.callService("input_datetime", "set_datetime", {
        entity_id: entity,
        timestamp: Math.floor(Date.now() / 1000),
      });
      return;
    }

    fireEvent(this, "hass-notification", {
      message:
        `plant-card: cannot log to ${entity} — tapping writes to datetime or ` +
        `input_datetime entities. Set water_script / fertilize_script instead.`,
    });
  }
}

/* ------------------------------------------------------------------------- *
 * Visual editor
 * ------------------------------------------------------------------------- */

const CARE_ENTITY_DOMAINS = ["datetime", "input_datetime"];

// ha-form flattens sections whose name is "", so the config stays a flat map.
const EDITOR_SCHEMA = [
  { name: "entity", selector: { entity: { domain: "sensor" } } },
  {
    name: "",
    type: "grid",
    schema: [
      { name: "name", selector: { text: {} } },
      { name: "icon", selector: { icon: {} } },
    ],
  },
  {
    name: "",
    type: "grid",
    schema: [
      {
        name: "water_interval",
        selector: { number: { min: 1, max: 365, step: 1, mode: "box" } },
      },
      {
        name: "fertilize_interval",
        selector: { number: { min: 1, max: 365, step: 1, mode: "box" } },
      },
    ],
  },
  {
    name: "",
    type: "expandable",
    title: "Entities",
    icon: "mdi:database",
    schema: [
      {
        name: "last_watered",
        selector: { entity: { domain: CARE_ENTITY_DOMAINS } },
      },
      {
        name: "last_fertilized",
        selector: { entity: { domain: CARE_ENTITY_DOMAINS } },
      },
      {
        name: "temperature",
        selector: { entity: { domain: "sensor", device_class: "temperature" } },
      },
      {
        name: "humidity",
        selector: { entity: { domain: "sensor", device_class: "humidity" } },
      },
      {
        name: "illuminance",
        selector: { entity: { domain: "sensor", device_class: "illuminance" } },
      },
      { name: "moisture", selector: { entity: { domain: "sensor" } } },
    ],
  },
  {
    name: "",
    type: "expandable",
    title: "Appearance and behaviour",
    icon: "mdi:palette",
    schema: [
      { name: "image", selector: { text: {} } },
      {
        name: "",
        type: "grid",
        schema: [
          { name: "tap_to_log", selector: { boolean: {} } },
          { name: "confirm", selector: { boolean: {} } },
          { name: "show_progress", selector: { boolean: {} } },
        ],
      },
      {
        name: "",
        type: "grid",
        schema: [
          { name: "water_label", selector: { text: {} } },
          { name: "fertilize_label", selector: { text: {} } },
        ],
      },
    ],
  },
];

const EDITOR_LABELS = {
  entity: "Plant (Plant Care summary entity)",
  name: "Name",
  icon: "Icon",
  image: "Image URL",
  water_interval: "Watering interval (days)",
  fertilize_interval: "Fertilizing interval (days)",
  last_watered: "Last watered",
  last_fertilized: "Last fertilized",
  temperature: "Temperature",
  humidity: "Humidity",
  illuminance: "Light",
  moisture: "Soil moisture",
  tap_to_log: "Tap a row to log care",
  confirm: "Confirm with a second tap",
  show_progress: "Show progress bars",
  water_label: "Watering label",
  fertilize_label: "Fertilizing label",
};

const EDITOR_HELPERS = {
  entity: "Supplies the name, timestamps, intervals and sensors. Everything below is optional and overrides it.",
  last_watered: "Only needed without a summary entity above.",
};

/** Drop blank values so cleared fields leave the YAML rather than sit empty. */
function pruneConfig(data) {
  const config = { type: "custom:plant-card" };
  for (const [key, value] of Object.entries(data || {})) {
    if (value === "" || value === undefined || value === null) continue;
    config[key] = value;
  }
  return config;
}

class PlantCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;

    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) =>
        EDITOR_LABELS[schema.name] || schema.title || schema.name;
      this._form.computeHelper = (schema) => EDITOR_HELPERS[schema.name];
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        fireEvent(this, "config-changed", {
          config: pruneConfig(ev.detail.value),
        });
      });
      this.appendChild(this._form);
    }

    this._form.hass = this._hass;
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = this._config;
  }
}

/* ------------------------------------------------------------------------- *
 * Registration
 * ------------------------------------------------------------------------- */

// Guarded: the integration loads this module itself, and a leftover manual
// Lovelace resource would otherwise load it a second time and throw on
// define(), taking the whole dashboard down with it.
if (!customElements.get("plant-card-editor")) {
  customElements.define("plant-card-editor", PlantCardEditor);
}

if (!customElements.get("plant-card")) {
  customElements.define("plant-card", PlantCard);
}

// This is what puts the card in the "Add card" picker.
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "plant-card")) {
  window.customCards.push({
    type: "plant-card",
    name: "Plant Card",
    description:
      "Track when a plant was last watered and fertilized, with its environment sensors.",
    preview: true,
    documentationURL: "https://github.com/albertsola/homeassistant-plant",
  });
}

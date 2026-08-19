/**
 * plant-card — a Lovelace card for tracking plant care.
 *
 * Shows when a plant was last watered and last fertilized (as relative time
 * plus a progress bar towards the next due date), and an optional row of
 * environment sensors (temperature, humidity, illuminance, soil moisture).
 *
 * No build step: this file is the distributable. Plain custom element, no
 * framework, so it keeps working across Home Assistant frontend releases.
 */

const CARD_VERSION = "1.0.0";

console.info(
  `%c PLANT-CARD %c ${CARD_VERSION} `,
  "color:#fff;background:#43a047;font-weight:700",
  "color:#43a047;background:#f1f8e9"
);

const UNAVAILABLE = ["unknown", "unavailable", "none", ""];

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
  static getStubConfig() {
    return {
      type: "custom:plant-card",
      name: "Plant",
      last_watered: "input_datetime.plant_last_watered",
      last_fertilized: "input_datetime.plant_last_fertilized",
      water_interval: 7,
      fertilize_interval: 30,
    };
  }

  setConfig(config) {
    if (!config || !config.last_watered) {
      throw new Error("plant-card: `last_watered` is required");
    }
    this._config = {
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
      ...config,
    };
    // Force a rebuild so a config change can never leave stale nodes behind.
    this._built = false;
    this._armed = null;
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    return this._config && this._sensorEntities().length ? 3 : 2;
  }

  _sensorEntities() {
    if (!this._config) return [];
    return SENSOR_ROW.filter((s) => this._config[s.key]).map((s) => ({
      ...s,
      entity: this._config[s.key],
    }));
  }

  _update() {
    if (!this._hass || !this._config) return;
    if (!this._built) this._build();
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

    if (!cfg.last_fertilized) {
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
      if (!item.entity) continue;

      const stateObj = hass.states[item.entity];
      const stamp = stampOf(stateObj);
      const elapsed = daysSince(stamp);
      const status = statusOf(elapsed, item.interval);

      el.row.classList.remove("ok", "soon", "overdue");
      el.row.classList.add(status);

      if (!stateObj) {
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

    if (!entity.startsWith("input_datetime.")) {
      fireEvent(this, "hass-notification", {
        message:
          `plant-card: cannot log to ${entity} — tapping only writes to ` +
          `input_datetime entities. Set water_script / fertilize_script instead.`,
      });
      return;
    }

    this._hass.callService("input_datetime", "set_datetime", {
      entity_id: entity,
      timestamp: Math.floor(Date.now() / 1000),
    });
  }
}

customElements.define("plant-card", PlantCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "plant-card",
  name: "Plant Card",
  description: "Track when a plant was last watered and fertilized, with its environment sensors.",
  preview: false,
  documentationURL: "https://github.com/asola/homeassistant-plant",
});

# plant-card

A Home Assistant Lovelace card for plant care: **when was this plant last
watered, and when was it last fertilized** — logged by a single physical
button (ON = water, OFF = fertilizer) — plus the plant's temperature, humidity
and light sensors.

```
┌──────────────────────────────┐
│ 🪴  Monstera                 │
│     Needs water              │
├──────────────────────────────┤
│ 💧 Watered      2 days ago   │
│ 🌱 Fertilized  18 days ago   │
├──────────────────────────────┤
│ 🌡 21.4 °C  💧 48 %  ☀ 1240 lx │
└──────────────────────────────┘
```

The card is plain JavaScript with **no build step** — `dist/plant-card.js` is
the shipped file.

## What's in here

| Path | What it is |
| --- | --- |
| `dist/plant-card.js` | The custom Lovelace card. |
| `packages/plant_care.yaml` | Helpers, button automation, and derived sensors. |
| `lovelace-example.yaml` | Card configuration examples. |

## How it works

1. A **physical button** (Zigbee/Z-Wave/BLE) exposed as an `event` entity fires
   an `on` or `off` press.
2. An **automation** stamps the matching `input_datetime` helper with `now()` —
   `on` → last watered, `off` → last fertilized.
3. The **card** reads those helpers, renders them as relative time
   ("2 days ago"), and colours each row green → amber → red as the next care
   date approaches.
4. Tapping a row on the card logs care manually (confirm-on-second-tap), so you
   don't need the button to be in reach.

## Install

### 1. Backend

Enable packages in `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Copy `packages/plant_care.yaml` into `<config>/packages/`, then edit it:

- replace `event.monstera_button` with your button entity,
- rename the `monstera` slug throughout for your own plant,
- duplicate every `monstera` block for each additional plant.

Restart Home Assistant (new `input_datetime` / `input_number` helpers need a
restart; later automation edits only need a reload).

### 2. Card

**HACS** — add this repository as a custom repository of type *Dashboard*,
install it, and HACS registers the resource for you.

**Manual** — copy `dist/plant-card.js` to `<config>/www/plant-card.js`, then
add the resource under *Settings → Dashboards → ⋮ → Resources*:

| Field | Value |
| --- | --- |
| URL | `/local/plant-card.js` |
| Type | JavaScript module |

Hard-refresh the browser afterwards (`Ctrl`/`Cmd` + `Shift` + `R`).

### 3. Add the card

```yaml
type: custom:plant-card
name: Monstera
last_watered: input_datetime.monstera_last_watered
last_fertilized: input_datetime.monstera_last_fertilized
temperature: sensor.monstera_temperature
humidity: sensor.monstera_humidity
illuminance: sensor.monstera_illuminance
```

## Card options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `last_watered` | entity | **required** | `input_datetime` (or timestamp sensor) holding the last watering. |
| `last_fertilized` | entity | – | Same for fertilizer. Omitted → the row is hidden. |
| `name` | string | `Plant` | Card title. |
| `icon` | icon | `mdi:flower` | Avatar icon. |
| `image` | url | – | Photo instead of the icon, e.g. `/local/plants/monstera.jpg`. |
| `water_interval` | number | `7` | Days before watering counts as overdue. |
| `fertilize_interval` | number | `30` | Days before fertilizing counts as overdue. |
| `temperature` | entity | – | Sensor shown in the bottom row. |
| `humidity` | entity | – | Sensor shown in the bottom row. |
| `illuminance` | entity | – | Sensor shown in the bottom row. |
| `moisture` | entity | – | Soil moisture sensor shown in the bottom row. |
| `water_label` | string | `Watered` | Row label. |
| `fertilize_label` | string | `Fertilized` | Row label. |
| `tap_to_log` | bool | `true` | Tapping a care row logs that care event. |
| `confirm` | bool | `true` | Require a second tap within 4 s before logging. |
| `show_progress` | bool | `true` | Thin bar showing elapsed time towards the interval. |
| `water_script` | `script.x` | – | Call this instead of writing the helper directly. |
| `fertilize_script` | `script.x` | – | Same, for fertilizer. |

Relative times are localized with the frontend's language. Tapping a sensor
opens its more-info dialog.

## Entities the package creates

| Entity | Purpose |
| --- | --- |
| `input_datetime.monstera_last_watered` | Timestamp of the last watering. |
| `input_datetime.monstera_last_fertilized` | Timestamp of the last fertilizing. |
| `input_number.monstera_water_interval` | Watering interval, adjustable from the UI. |
| `input_number.monstera_fertilize_interval` | Fertilizing interval. |
| `sensor.monstera_days_since_watered` | Days elapsed — for automations and history graphs. |
| `sensor.monstera_days_since_fertilized` | Days elapsed. |
| `binary_sensor.monstera_needs_water` | `on` when past the interval. |
| `binary_sensor.monstera_needs_fertilizer` | `on` when past the interval. |
| `script.plant_log_care` | Stamps any care helper with `now()`. |

The `input_number` intervals drive the binary sensors and the optional
reminder; the card's own colour thresholds come from its YAML
`water_interval` / `fertilize_interval`.

## Other button types

`packages/plant_care.yaml` ends with drop-in trigger blocks for Zigbee2MQTT
payloads, UI device triggers, and a plain switch / `input_boolean`.

One gotcha the package already handles: on an `event` entity, pressing the same
button twice in a row does **not** change the `event_type` attribute — only the
entity's state (the event timestamp) changes. Triggering on
`attribute: event_type` therefore silently drops repeated presses, so the
automation triggers on the state and reads the type in a condition.

## Reminders

A daily "your plant is thirsty" notification is included, commented out, at the
bottom of `packages/plant_care.yaml` — move it into the `automation:` block to
enable it.

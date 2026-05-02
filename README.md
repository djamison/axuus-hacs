# Axuus HACS Integration

[![Tests](https://github.com/djamison/axuus-hacs/actions/workflows/tests.yml/badge.svg)](https://github.com/djamison/axuus-hacs/actions/workflows/tests.yml)
[![HACS Validation](https://github.com/djamison/axuus-hacs/actions/workflows/validate.yml/badge.svg)](https://github.com/djamison/axuus-hacs/actions/workflows/validate.yml)

Home Assistant custom integration for [Axuus](https://axuus.com) gated-community access. Not affiliated with Axuus.

Polls the Axuus resident portal and exposes your gate access codes, vehicles, and authorization controls as Home Assistant entities, services, and events.

## Features

- **Access code sensors** — one sensor per active code (state = 6-digit code, attributes for description, expiry, times used)
- **Vehicle authorization switches** — toggle gate access per vehicle from your dashboard or automations
- **Aggregate count sensors** — active codes, resident vehicles, guest vehicles at a glance
- **Connection status** — binary sensor showing whether the last poll succeeded
- **Refresh button** — trigger an immediate data refresh without waiting for the next poll
- **HA bus events** — `axuus_code_created`, `axuus_code_used`, `axuus_code_expired`, `axuus_vehicle_added`, `axuus_vehicle_removed` for automation triggers
- **Services** — `axuus.create_code`, `axuus.update_code`, `axuus.delete_code`, `axuus.authorize_vehicle`, `axuus.remove_vehicle`, `axuus.refresh`

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Go to **Integrations** → three-dot menu → **Custom repositories**
3. Add `https://github.com/djamison/axuus-hacs` with category **Integration**
4. Search for "Axuus" and install
5. Restart Home Assistant

### Manual

Copy the `custom_components/axuus/` directory into your Home Assistant `config/custom_components/` folder and restart.

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Axuus**
3. Choose your authentication method:
   - **Email + password** — your Axuus portal credentials
   - **Paste cookie** — paste the `.ASPXAUTH` cookie value from your browser's DevTools (fallback if captcha is enforced)
4. The integration validates your credentials by fetching your access codes

### Options

After setup, click **Configure** on the integration card to adjust:

- **Poll interval** — how often to check for updates (30–600 seconds, default 60)

The poll interval updates live without restarting the integration.

## Entities

All entities are grouped under a single **Axuus** device in the HA device registry.

| Entity | Type | Description |
|---|---|---|
| `sensor.axuus_code_{id}` | Sensor | One per active access code. State = 6-digit code. Attributes: description, expires_after, assign_lp, date_created, times_used, is_one_time |
| `sensor.axuus_active_codes_count` | Sensor | Number of active access codes |
| `sensor.axuus_resident_vehicles_count` | Sensor | Number of resident vehicles |
| `sensor.axuus_guest_vehicles_count` | Sensor | Number of guest vehicles |
| `switch.axuus_{vehicle_id}_authorized` | Switch | Gate authorization toggle per vehicle. ON = authorized, OFF = unauthorized |
| `button.axuus_refresh` | Button | Trigger an immediate data refresh |
| `binary_sensor.axuus_connection` | Binary Sensor | ON when the last poll succeeded, OFF on failure |

Codes and vehicles that disappear between polls are marked **unavailable** rather than removed, preserving any automations that reference them.

## Services

### `axuus.create_code`

Create a new gate access code.

| Field | Required | Description |
|---|---|---|
| `description` | Yes | Description for the code |
| `expires_after` | Yes | `onetime`, `oneday`, `threedays`, `oneweek`, or `onemonth` |
| `assign_lp` | No | Auto-add visitor's license plate on use (default: false) |
| `email_to` | No | Email address to send the code to |
| `sms_to` | No | Phone number to send the code to |

### `axuus.update_code`

Update an existing access code.

| Field | Required | Description |
|---|---|---|
| `code_id` | Yes | The ID of the code to update |
| `description` | No | New description |
| `assign_lp` | No | Auto-add visitor's license plate on use |
| `email_to` | No | Email address |
| `sms_to` | No | Phone number |

### `axuus.delete_code`

Delete an access code.

| Field | Required | Description |
|---|---|---|
| `code_id` | Yes | The ID of the code to delete |

### `axuus.authorize_vehicle`

Set a vehicle's gate authorization state. Idempotent — no API call if already in the desired state.

| Field | Required | Description |
|---|---|---|
| `vehicle_id` | Yes | The vehicle ID |
| `authorized` | Yes | `true` to authorize, `false` to unauthorize |

### `axuus.remove_vehicle`

Soft-remove a vehicle from your Axuus account. This does **not** revoke gate access — contact Axuus staff for that.

| Field | Required | Description |
|---|---|---|
| `vehicle_id` | Yes | The vehicle ID |
| `confirm` | Yes | Must be `true` to proceed |

### `axuus.refresh`

Trigger an immediate data refresh from the Axuus portal. No fields.

## Events

The integration fires events on the HA bus when changes are detected between poll cycles:

| Event | Fired when | Data fields |
|---|---|---|
| `axuus_code_created` | New code appears | code_id, code, description, expires_after, is_one_time |
| `axuus_code_used` | Code's times_used increases | code_id, code, description, times_used, previous_times_used |
| `axuus_code_expired` | Code disappears from active list | code_id, code, description, was_one_time |
| `axuus_vehicle_added` | New vehicle appears | vehicle_id, lp_num, lp_state, description, vehicle_type |
| `axuus_vehicle_removed` | Vehicle disappears | vehicle_id, lp_num, description, vehicle_type, removed_via |

## Automation Examples

### Schedule a weekly cleaner code

```yaml
automation:
  - alias: "Cleaner — Tuesday 9 AM code"
    trigger:
      - platform: time
        at: "08:55:00"
    condition:
      - condition: time
        weekday: [tue]
    action:
      - service: axuus.create_code
        data:
          description: "Cleaner {{ now().strftime('%Y-%m-%d') }}"
          expires_after: oneday
          assign_lp: false
```

### Notify when a code is used

> **Note:** Code usage is detected by polling, so this notification may be delayed by up to one poll interval (default 60 seconds).

```yaml
automation:
  - alias: "Notify on code use"
    trigger:
      - platform: event
        event_type: axuus_code_used
    action:
      - service: notify.mobile_app
        data:
          title: "Gate code used"
          message: >
            Code {{ trigger.event.data.code }} ({{ trigger.event.data.description }})
            was used. Total uses: {{ trigger.event.data.times_used }}
```

### Create a code and delete it after 2 hours

```yaml
automation:
  - alias: "Temporary 2-hour code"
    trigger:
      - platform: event
        event_type: axuus_code_created
        event_data:
          description: "Temp Access"
    action:
      - delay: "02:00:00"
      - service: axuus.delete_code
        data:
          code_id: "{{ trigger.event.data.code_id }}"
```

## Limitations

- **No arbitrary expiry timestamps** — Axuus only supports `onetime`/`oneday`/`threedays`/`oneweek`/`onemonth`. For exact end-times, schedule a separate `axuus.delete_code` call.
- **Vehicle removal is soft** — `axuus.remove_vehicle` calls InactivateVehicle, which removes the vehicle from your account view. For true gate-level revocation, contact Axuus staff.
- **No webhooks** — Axuus has no push mechanism. All state changes are detected by polling and diffing. Events may be delayed by up to one poll interval.
- **Authorization state requires per-vehicle calls** — Vehicle listings don't include the `Ver_Auth` flag. The integration calls `GetVehicle` for each vehicle on first poll and when new vehicles appear.

## Development

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest                    # 84 tests (unit + property-based)
ruff check .              # lint
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on contributing.

## License

MIT — see [LICENSE](LICENSE).

# axuus-hacs

Home Assistant integration for [Axuus](https://axuus.com) gated-community access. Not affiliated with Axuus.

**Status:** scaffold. API client + tests. No HA platforms wired up yet.

## What it will do

- Show your **Axuus+ codes** as sensor entities (state = the 6-digit code; attributes for description, expiry, times used)
- Show your **resident vehicles** and **guest vehicles** as devices with a `switch` for authorization
- Fire HA bus events when codes are created, used, or expire (poll-and-diff — Axuus has no webhooks)
- Provide services: `axuus.create_code`, `axuus.update_code`, `axuus.delete_code`, `axuus.create_vehicle`, `axuus.authorize_vehicle`, `axuus.remove_vehicle`

See [DESIGN.md](research/DESIGN.md) for the full spec and reverse-engineering notes.

## What it will not do

- Set arbitrary code expiry timestamps — Axuus only supports the enum `onetime`/`oneday`/`threedays`/`oneweek`/`onemonth`. For exact end-times, schedule a separate delete in HA.
- Truly delete a vehicle — Axuus has no such endpoint. `axuus.remove_vehicle` calls Inactivate (soft remove from your account view); for full gate-level revocation contact Axuus support.

## Development

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

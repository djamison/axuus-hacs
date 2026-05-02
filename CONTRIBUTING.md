# Contributing to Axuus HACS

Thanks for your interest in contributing! This project is open to forks, issues, and pull requests.

## Getting Started

```sh
git clone https://github.com/djamison/axuus-hacs.git
cd axuus-hacs
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

All 84 tests should pass before you start making changes.

## Project Structure

```
custom_components/axuus/
├── api/                  # HTTP client (stable, tested — modify with care)
│   ├── client.py         # AxuusClient: login, list, mutate
│   ├── models.py         # AccessCode, Vehicle dataclasses
│   └── exceptions.py     # AxuusError hierarchy
├── __init__.py           # Integration setup/teardown + service handlers
├── config_flow.py        # Config flow (auth, reauth, options)
├── coordinator.py        # DataUpdateCoordinator + diff engine
├── sensor.py             # Per-code + aggregate count sensors
├── switch.py             # Per-vehicle authorization toggle
├── button.py             # Refresh button
├── binary_sensor.py      # Connection status
├── services.yaml         # Service definitions
├── strings.json          # Config flow UI strings
├── translations/en.json  # Runtime translations
├── const.py              # Constants
└── manifest.json         # HA integration manifest
```

## How to Contribute

### Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Your HA version and integration version
- Relevant logs (Settings → System → Logs, filter for `axuus`)

### Pull Requests

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Add or update tests for any new behavior
4. Run the full test suite: `pytest tests/ -v`
5. Run the linter: `ruff check custom_components/ tests/`
6. Open a PR with a clear description of what changed and why

### Code Style

- Python 3.13+, async/await throughout
- Follow existing patterns in the codebase
- Use `ruff` for linting (config in `pyproject.toml`)
- Type hints on all function signatures
- Docstrings on public classes and functions

### Testing

The project uses three layers of tests:

- **Unit tests** (`tests/test_*.py`) — mock HA internals, test individual components
- **Property-based tests** (`tests/test_*_properties.py`) — use [Hypothesis](https://hypothesis.readthedocs.io/) to verify correctness properties hold for arbitrary inputs
- **API client tests** (`tests/test_client.py`, `tests/test_models.py`) — mock HTTP responses, verify request shapes

When adding a new entity or service, add both unit tests and consider whether a property-based test would strengthen coverage.

### Areas Where Help Is Welcome

- **Smoke testing on real HA instances** — the unit tests mock HA internals; real-world testing catches wiring issues
- **Additional entity platforms** — e.g., per-vehicle sensor with LP/make/model attributes
- **Blueprints** — reusable automation templates (scheduled code creation, timed deletion)
- **Localization** — translations beyond English
- **CI improvements** — integration tests with `pytest-homeassistant-custom-component`
- **Documentation** — better automation examples, troubleshooting guides

## API Notes

The Axuus portal is a reverse-engineered ASP.NET WebForms site. There are no public API docs. Key quirks:

- `AuthorizeVehicle` is a **toggle** — you send the *current* state and the server flips it
- `InactivateVehicle` is a **soft remove** — does not revoke gate access
- Vehicle listings don't include authorization state — requires per-vehicle `GetVehicle` calls
- reCAPTCHA is loaded but not enforced (as of 2026-05-01) — could change at any time

See `research/DESIGN.md` for the full reverse-engineering spec.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

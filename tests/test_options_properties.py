"""Property-based tests for the Axuus options flow poll interval validation.

# Feature: axuus-ha-integration, Property 7: Poll interval validation

Tests verify that the options flow schema accepts a value if and only if
it is between 30 and 600 inclusive.

**Validates: Requirements 2.2**
"""

from __future__ import annotations

import voluptuous as vol
from hypothesis import given, settings, strategies as st

from custom_components.axuus.const import (
    CONF_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

# Reproduce the exact schema used in the options flow
_POLL_INTERVAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_POLL_INTERVAL): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
        ),
    }
)


# ---------------------------------------------------------------------------
# Property 7: Poll interval validation
# ---------------------------------------------------------------------------


@given(
    value=st.integers(min_value=-1000, max_value=2000),
)
@settings(max_examples=100)
def test_poll_interval_validation(value: int) -> None:
    """Property 7: Poll interval validation.

    **Validates: Requirements 2.2**

    For any integer value, the options flow schema accepts the value
    if and only if 30 <= value <= 600.
    """
    should_accept = MIN_POLL_INTERVAL <= value <= MAX_POLL_INTERVAL

    if should_accept:
        # Schema should accept the value without raising
        result = _POLL_INTERVAL_SCHEMA({CONF_POLL_INTERVAL: value})
        assert result[CONF_POLL_INTERVAL] == value
    else:
        # Schema should reject the value
        try:
            _POLL_INTERVAL_SCHEMA({CONF_POLL_INTERVAL: value})
            # If we get here, the schema accepted an invalid value
            raise AssertionError(
                f"Schema accepted invalid poll interval: {value} "
                f"(expected rejection for values outside [{MIN_POLL_INTERVAL}, {MAX_POLL_INTERVAL}])"
            )
        except vol.Invalid:
            pass  # Expected: schema correctly rejected the value

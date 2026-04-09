# Home Assistant: OBD2 (TCP)

Custom integration that connects to an **ELM327-compatible** adapter over **TCP** (host and port), polls OBD-II data, and evaluates **CALC** expressions compatible with [obd2-mqtt](https://github.com/adlerre/obd2-mqtt) profile JSON.

## Requirements

- Home Assistant 2024.1 or newer
- An OBD2 adapter that exposes the ELM327 serial protocol on a TCP port (Wi‑Fi bridges often use ports such as `35000`; check your device manual)

## Installation (manual)

1. Copy the `custom_components/obd2_tcp` folder into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & services → Add integration → OBD2 (TCP)**.

## Installation (HACS)

Add this repository as a custom repository (category: Integration), then install **OBD2 TCP** and restart Home Assistant.

## Configuration

| Field | Description |
|--------|-------------|
| Host | IP or hostname of the adapter |
| Port | TCP port (default `35000`) |
| Scan interval | How often the coordinator runs a poll cycle (seconds). Profile `interval` values are in **milliseconds**; a state is only updated when both this cycle and its interval allow it. |
| Device name | Friendly name for the device |
| Profile | Name of a JSON file in `custom_components/obd2_tcp/profiles/` without `.json` (default: `default`) |
| Fuel type | Default fuel type code when `$fuelType` is used in expressions and no `fuelType` READ state exists (matches obd2-mqtt `obd.h` constants; `1` = gasoline) |

## Profiles

Profiles use the same array shape as obd2-mqtt `profiles/*.json`: **READ** (`type`: 0) and **CALC** (`type`: 1), `pid` decimals, `scaleFactor` expressions, and `expr` for CALC.

Place additional profiles next to `default.json`. Trig functions in CALC use **degrees**, matching the firmware `ExprParser`.

## Behavior notes

- Only **one client** should talk to the ELM at a time.
- State and CALC values are **runtime only** (not restored after HA restart); distance-style CALC accumulators reset like a cold start unless you add restore logic later.
- Unsupported READ modes other than service **01** (and `readFunc` **batteryVoltage** via `AT RV`) are skipped.

## Development

Syntax check (no Home Assistant required for parser tests):

```bash
python3 -m compileall custom_components/obd2_tcp
python3 -m pytest tests/ -q
```

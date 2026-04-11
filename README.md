# Home Assistant: OBD2 (TCP)

Custom integration that connects to an **ELM327-compatible** adapter over **TCP** (host and port), polls OBD-II data, and evaluates **CALC** expressions compatible with [obd2-mqtt](https://github.com/adlerre/obd2-mqtt) profile JSON.

Under the hood it uses [python-OBD](https://github.com/brendan-w/python-OBD) (PyPI package `obd`) and connects via a pySerial URL like `socket://<host>:<port>`.

## Requirements

- Home Assistant 2024.1 or newer
- An OBD2 adapter that exposes the ELM327 serial protocol on a TCP port (Wi‑Fi bridges often use ports such as `35000`; check your device manual)

## Wi‑Fi adapters: VGate iCar (LPT230 + ELM327)

**Testing note:** The **Disable ELM327 low power** feature (PP0E `ATPP…` / `ATPP0EON`) has only been exercised on **VGate iCar 2 / iCar Pro Wi‑Fi**-class hardware. Other ELM327 devices may use **different programmable-parameter layouts** or NVM semantics; sending PP writes meant for the iCar **can corrupt firmware settings or render an adapter unusable** (“bricked”) until factory reset or vendor repair. **Do not enable that option** unless you are sure your dongle matches the documented iCar behavior.

Many **VGate iCar 2 / iCar Pro Wi‑Fi** units pair an ELM327 with a **Hi‑Flying LPT230** UART‑to‑Wi‑Fi module. Out of the box they often act as an AP (SSID **V‑LINK**), with **TCP port `35000`** giving transparent access to the ELM serial stream. Detailed hardware notes, web UI paths, and ELM **programmable parameter** examples are in **[dconlon/icar_obd_wifi](https://github.com/dconlon/icar_obd_wifi)**.

### Station mode (join your home Wi‑Fi)

1. Connect to the adapter’s AP (**V‑LINK**), then open **`http://192.168.0.10`** in a browser.
2. Sign in (reported combinations include **`guest` / `&^)@@)`** and **`admin` / `admin`**; the repo also mentions querying credentials via **`AT+WEBU`** on the LPT230).
3. Switch the module to **station** mode and your SSID so the dongle gets a DHCP address on your LAN. It should keep listening for **TCP on port `35000`** on that IP (confirm with your device or the Hi‑Flying config tool if something differs).

If you lose access to the Wi‑Fi module, a **factory reset** is often done by jumpering **LPT230 pin 12 (nReload) to pin 16 (GND)** for several seconds (see the repo’s photos). That restores the default open‑AP layout so you can reconfigure.

### ELM low power vs Wi‑Fi sleep

On these devices, **when the ELM327 enters low‑power mode** (reported as about **20 minutes** of no activity by default), the **Wi‑Fi can shut down** until you press the dongle’s **power button**. That is separate from “poll more often” — it is ELM firmware policy.

To **turn off those low‑power behaviors** (persistent until changed), the community approach is to adjust **programmable parameter PP0E** per the ELM327 datasheet, then save:

- Send **`ATPP0ESV7A`** (example: clear the low‑power bit; value **`7A`** matches one reported stock mask **`FA` → `7A`** — verify on your chip if unsure).
- Send **`ATPP0EON`** to store the change; **power‑cycle** the adapter so it takes effect.

The integration can send these commands automatically if you enable **Disable ELM327 low power** during setup or in **Configure** — **only on hardware you know is compatible** (see the testing note above). Alternatively use any raw ELM terminal on **TCP `35000`** (e.g. `nc`, a serial terminal app, or python‑OBD’s `interface.send_and_parse`). **Clones may not implement PP commands identically**; wrong PP values can cause odd behavior or worse, so treat this as optional tuning and read your ELM327 documentation.

## Installation (manual)

1. Copy the `custom_components/obd2_tcp` folder into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & services → Add integration → OBD2 (TCP)**.

## Installation (HACS)

Add this repository as a custom repository (category: Integration), then install **OBD2 TCP** and restart Home Assistant.

## Configuration

| Field | Description |
| ------ | ----------- |
| Host | IP or hostname of the adapter |
| Port | TCP port (default `35000`) |
| Scan interval | How often the coordinator runs a poll cycle (seconds). Profile `interval` values are in **milliseconds**; a state is only updated when both this cycle and its interval allow it. |
| Device name | Friendly name for the device |
| Profile | Name of a JSON file in `custom_components/obd2_tcp/profiles/` without `.json` (default: `default`) |
| Fuel type | Default fuel type code when `$fuelType` is used in expressions and no `fuelType` READ state exists (matches obd2-mqtt `obd.h` constants; `1` = gasoline) |
| Disable ELM327 low power | **VGate iCar‑class only (tested).** Other adapters risk **brick / corrupted NVM**. On the **display units** step or **Configure**: sends `ATPP0ESV7A` then `ATPP0EON` on the **first successful connect** each Home Assistant run (`7A` PP0E — see **Wi‑Fi adapters**). **Power‑cycle** the dongle if Wi‑Fi still sleeps. Turn off after PP is stored if you prefer not to re‑send on every restart. |

## Profiles

### MIL and monitor status

**MIL** (*Malfunction Indicator Lamp*) is the **check engine light**. OBD **PID 01** (monitor status) reports whether the MIL is commanded **on**, how many **emissions-related DTCs** the ECU reports, and **readiness** flags for smog-related monitors. That is separate from reading the actual trouble codes (**mode 03**), which the integration can do when a CALC uses `numDTCs(...)`.

The **`ford_e450_2013`** profile exposes a **32-bit bitstring** for PID 01, a **check engine** boolean, DTC counts, raw readiness bytes B/C/D, and extra PIDs where supported. Set **`enabled`: false** on any entity that returns **NO DATA** on your bus.

Profiles use the same array shape as obd2-mqtt `profiles/*.json`: **READ** (`type`: 0) and **CALC** (`type`: 1), `pid` decimals, `scaleFactor` expressions, and `expr` for CALC.

Place additional profiles next to `default.json`. Trig functions in CALC use **degrees**, matching the firmware `ExprParser`.

### RV / house loads (Ford E‑450 profile)

The **`ford_e450_2013`** profile aligns **standard OBD‑II** with names you see in **FORScan** freeze data (e.g. **IAT**, **ECT**, **BARO**, **LOAD**, **FLI**, **RUNTM**, **VPWR**). It does **not** expose FORScan‑only items such as **TAC_PCT**, **TFT**, **GEAR**, or **APP** voltages — those need manufacturer‑specific modes (FORScan), not mode `01` alone.

For **alternator → house bank** or **AC** automations, combine entities such as **`rpm`**, **`engineLoad`**, **`controlModuleVoltage`** (≈ FORScan **VPWR**), **`alternatorHeadroomVolts`** (heuristic delta), **`engineLoadPowerProxy`** (RPM×load heuristic), and temperatures. **`batteryVoltage`** is **AT RV** (adapter pin 16), not the same as **VPWR**. Your export shows **P0620** (generator control) — worth monitoring **`checkEngineLight`** / DTCs alongside charging logic.

Bundled example: **`ford_e450_2013`** — tuned for a **2013 Ford E‑450**-class chassis from ELM probe output: **MIL / PID 01** (bitstring, check-engine bool, DTC counts, readiness bytes), **timing advance** (`010E`), **distance with MIL** (`0121`), fuel trims, MAF, lambda, relative throttle, fuel-type code, plus the earlier core PIDs. **Omitted** intake MAP (`010B`) and oil temp (`015C`) (**NO DATA** on that bus). Disable any new PID that returns **NO DATA** on yours. PID support **81–C0** (`0180` / `01A0`) often shows NO DATA even when the bus is healthy.

### Adapter probe (run on your LAN)

From a machine that can reach the adapter:

```bash
python3 tools/obd_probe.py 192.168.x.x -p 35000
```

Use **`--quick`** for identity + `AT RV` only. Full run prints supported-PID bitmaps (`0100`, `0120`, …), sample PIDs, and mode `03` DTCs — use the output to tune your profile.

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

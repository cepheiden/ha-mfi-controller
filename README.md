<p align="center">
  <img src="custom_components/mfi_controller/brand/icon@2x.png" width="128" alt="mFi Controller icon">
</p>

# mFi Controller for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/cepheiden/ha-mfi-controller/actions/workflows/validate.yml/badge.svg)](https://github.com/cepheiden/ha-mfi-controller/actions/workflows/validate.yml)

**Use Home Assistant as the controller for Ubiquiti mFi mPower power strips, so the old Java mFi Controller can be retired.**

The mFi product line is end-of-life, and the official controller is an old Java/MongoDB
application. Running the strips without any controller causes problems: the web UI hangs
and Wi-Fi units drop off the network until they are power-cycled. This integration
implements the controller side of Ubiquiti's *inform* protocol, so the devices keep working
exactly as designed, only now they report to Home Assistant.

## Features

- **Local push.** The device sends its readings every 10 s; Home Assistant does not poll it.
- **Fast switching.** Like the original controller, Home Assistant sends a UDP wake-up to
  the device and returns the switch command in the device's next report. In tests the outlet
  switched about 0.2 s after the command, and Home Assistant confirmed the change about 1.5 s later.
- **Per outlet:** switch, power (W), energy this month (kWh, `total_increasing`, works in the
  Energy dashboard), current (A), voltage (V), power factor (%), energy last month (disabled by default).
- **Per device:** total power, IP address (diagnostic; SSID/BSSID/firmware/uptime as attributes).
- **Guided setup over SSH.** It reads the MAC address, outlet names and key, then points the
  device to Home Assistant. Manual setup is also available.
- **No firmware modifications.** Only the device's inform URL is changed, and the previous
  setting is kept as a backup on the device.
- Diagnostics download (secrets redacted), English and German UI.

### Why not just poll the device's HTTP API?

Each HTTP request to the mPower starts a CGI process on a small embedded CPU. Measured on
an mPower (P3E, firmware 2.1.12):

| Mode | CPU busy on the device |
|---|---|
| Informs only (controller / this integration) | **~6 %** |
| Polling `/sensors` every 10 s | **~22 %** (each request takes ~2 s and ~1.6 s of CPU time) |
| Polling every 2 s | **~41 %** |

The inform reports are built by the device anyway, so receiving them costs it nothing extra.

## Supported devices

| Device | Status |
|---|---|
| mFi **mPower** (P3E, 3 outlets, Wi-Fi), firmware 2.1.12, previously adopted by an mFi Controller | ✅ tested |
| mPower mini (P1E), mPower Pro (P8E/P6E) | ⚠️ should work: same protocol, outlet count is read from the device. Please report! |
| Factory-reset mPower (never adopted) | ⚠️ supported by the SSH setup (a new key is generated), not tested yet |
| mPort, mFi sensors, mFi switches/dimmers | ❌ not supported (yet) |

Requires Home Assistant **2025.6** or newer.

## Before you start

You need:

1. **The IP address of the strip.** Your router's client list will show it. A DHCP reservation is recommended.
2. **The SSH login of the strip:**
   - Device was adopted by an mFi Controller: the controller sets the device login to the
     **controller's admin username and password**.
   - Factory-default device: `ubnt` / `ubnt`.
3. **Network access from the strip to Home Assistant** on
   - **TCP 6080** (inform reports and commands), and
   - **UDP 3478** (STUN replies and wake-up packets).

   Home Assistant OS, Supervised and Docker with `network_mode: host` work as is. For other
   Docker setups, publish both ports (`-p 6080:6080 -p 3478:3478/udp`). If the strip is on
   another VLAN, allow these ports in your firewall.
4. **A plan for your old controller.** Once the strip reports to Home Assistant, the old
   controller shows it as disconnected. You can keep the controller for rollback or remove it.
   Don't run both on the same host with the same ports.

## Installation

### HACS (recommended)

1. Open HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/cepheiden/ha-mfi-controller`, category **Integration**.
3. Search for **mFi Controller**, install it and **restart Home Assistant**.

### Manual

Copy `custom_components/mfi_controller` into the `custom_components` folder of your
Home Assistant configuration and restart.

## Setup

**Settings → Devices & services → Add integration → mFi Controller**

### Option A: Automatic (SSH), recommended

| Field | Meaning |
|---|---|
| Device IP / host | IP address of the strip |
| SSH username / password | see *Before you start* |
| Address of Home Assistant | IP address the **strip** uses to reach Home Assistant (pre-filled; check it if Home Assistant has several interfaces) |
| Inform port / STUN port | defaults 6080 / 3478 |
| Keep the existing key | recommended. Your old controller keeps working if you switch back |

What happens on the device:

1. Home Assistant reads `/etc/board.inc` (MAC address, model, outlet count),
   `/etc/persistent/cfg/mgmt` (key) and `/etc/persistent/cfg/config_file` (outlet names).
2. It copies `/etc/persistent/cfg/mgmt` to `/etc/persistent/cfg/mgmt.before-homeassistant`
   (only once), sets `mgmt.servers.1.url=http://<home-assistant>:6080/inform` and saves
   with `cfgmtd -w -p /etc/`. Writing to flash takes about 20 s.
3. It tells the running device to connect right away (`mca-ctrl -t connect …`).
4. Setup finishes as soon as the first report arrives (up to 90 s).

The SSH password is only used for this step and is **not stored**.

### Option B: Manual

Use this if you don't want Home Assistant to log into the device.

1. Find the key (32 hex characters):
   - on the device: `grep authkey /etc/persistent/cfg/mgmt`, or
   - in the old controller's MongoDB, database `ace`, collection `device`, field `x_authkey`.
     The MongoDB port depends on the installation (e.g. `37017` in the `fflo/mfi-controller` Docker image):
     `mongo --port 37017 ace --eval 'db.device.find({}, {mac:1, x_authkey:1}).forEach(printjson)'`
2. Point the device to Home Assistant:
   ```sh
   # immediately (lost on reboot)
   mca-ctrl -t connect -s http://<home-assistant-ip>:6080/inform -k <authkey>
   # permanently
   sed -i 's#^mgmt.servers.1.url=.*#mgmt.servers.1.url=http://<home-assistant-ip>:6080/inform#' /etc/persistent/cfg/mgmt
   cfgmtd -w -p /etc/
   ```
3. In Home Assistant choose **Manual**. Enter the MAC address (`board_hwaddr` from
   `/etc/board.inc`, which is the LAN MAC) and the key. Then wait for the first report.

Outlet names cannot be read in manual mode; the entities are called *Port 1…n*.
You can rename them in Home Assistant.

## Using it

- Add the **Energy** sensors under **Settings → Dashboards → Energy → Individual devices**.
  They are monthly counters kept by the device. When a new month starts, Home Assistant
  recognises the reset automatically.
- The switches work like any other switch. If the device is unreachable, the service call
  fails after 15 s with a clear error instead of pretending it worked.
- Entities become **unavailable** when the device has not reported for about 35 s.
- If the IP address of Home Assistant changes, remove the device and add it again (SSH setup), so the device learns the new URL.

## Rollback to the original controller

On the device (SSH):

```sh
cp /etc/persistent/cfg/mgmt.before-homeassistant /etc/persistent/cfg/mgmt
cfgmtd -w -p /etc/
reboot
```

Then start your old controller again and remove the integration entry in Home Assistant.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Setup: *SSH connection failed* | Wrong IP, or SSH disabled on the device. The device's SSH server is very slow and can take 10 s or more to answer. |
| Setup: *SSH login rejected* | An adopted device uses the controller's admin login, not `ubnt`/`ubnt`. |
| Setup: *device did not report within 90 s* | TCP 6080 is blocked between the device and Home Assistant, or the *Address of Home Assistant* is wrong. Check the URL with `grep servers /etc/persistent/cfg/mgmt`. |
| Setup: *port already in use* | Another service (e.g. a still-running mFi/UniFi controller on the same host) uses TCP 6080. Choose another inform port. |
| Values arrive, but switching is slow (up to 10 s) | UDP 3478 is blocked or not published, so the wake-up does not reach the device. Check *Diagnostics → `hub.stun_error`*. |
| Web UI/SSH of the strip hangs, strip drops off Wi-Fi | This happens when the strip had no working controller for a while, for example a long Home Assistant outage or a wrong URL. Unplug the strip briefly; it keeps its settings. |

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.mfi_controller: debug
```

## Security notes

- The inform traffic is encrypted with the device's own AES key, as with the original
  controller. The key is stored in the Home Assistant config entry and redacted in diagnostics.
- mFi firmware only supports legacy SSH algorithms (`diffie-hellman-group1-sha1`, `ssh-rsa`,
  `aes128-cbc`). They are enabled only for the one-time setup connection. Host keys are not checked.
  Future `cryptography` releases may drop these algorithms; manual setup will still work then.
- The mPower firmware also runs telnet (port 23) and an old web server. Keep these devices
  in a trusted network or an IoT VLAN.

## How it works

```
 mPower ── TCP POST /inform (AES, every 10 s) ──▶ Home Assistant :6080
        ◀── reply: noop {interval} | cmd mfi-output {port, val} ──
 mPower ◀── UDP "0x8888…" wake-up from :3478 (on switch) ── Home Assistant
        ── STUN binding request ──▶ :3478 ── binding response ──▶
```

Payloads are JSON (`alarm[]` holds one entry per outlet: `output`, `active_pwr`, `i_rms`,
`v_rms`, `pf`, `thismonth`, `lastmonth`). Protocol background:
[mcrute/ubntmfi](https://github.com/mcrute/ubntmfi/blob/master/inform_protocol.md).

## Development

```sh
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

The tests run against a simulated mPower (`tests/device_sim.py`) that speaks the real
protocol, including the UDP wake-up. The STUN reply is compared byte by byte with a capture
from the original mFi Controller 2.1.12. Translations are generated with
`python script/gen_translations.py`.

Reports for other models are welcome. Please attach the integration's diagnostics download
(secrets are redacted) and your firmware version.

## License

MIT. Not affiliated with or endorsed by Ubiquiti Inc.

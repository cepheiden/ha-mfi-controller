#!/usr/bin/env python3
"""Generate strings.json and translations/{en,de}.json from one source."""
import json
import pathlib

BASE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "mfi_controller"

T = {
    "en": {
        "menu": {"title": "Add mFi device", "description": "Home Assistant takes over the role of the Ubiquiti mFi controller.",
                 "ssh": "Automatic (SSH login of the device)", "manual": "Manual (MAC address + authkey)"},
        "ssh": {"title": "Adopt via SSH",
                "description": "Home Assistant logs into the device once over SSH, reads its key and points its inform URL to this server. A backup of the old setting is kept on the device.",
                "host": "Device IP / host", "username": "SSH username", "password": "SSH password",
                "inform_host": "Address of Home Assistant (as seen by the device)", "inform_port": "Inform port (TCP)",
                "stun_port": "STUN / wake-up port (UDP)", "keep_key": "Keep the existing key (old controller keeps working until the URL is switched back)"},
        "manual": {"title": "Manual setup",
                   "description": "Point the device to `http://HA_IP:PORT/inform` yourself (e.g. via SSH: `mca-ctrl -t connect -s URL -k AUTHKEY`, see README). Home Assistant waits for the first inform.",
                   "mac": "MAC address (as sent in the inform header)", "authkey": "Authkey (32 hex characters)",
                   "inform_port": "Inform port (TCP)", "stun_port": "STUN / wake-up port (UDP)"},
        "progress": {"provision": "Configuring the device and waiting for its first report (up to 90 s)...",
                     "wait": "Waiting for the first report of the device (up to 90 s)..."},
        "error": {"cannot_connect": "SSH connection failed", "invalid_auth": "SSH login rejected",
                  "provision_failed": "Configuring the device failed, see the log", "port_in_use": "Inform/STUN port is already in use",
                  "no_inform": "The device did not report within 90 s", "invalid_mac": "Invalid MAC address", "invalid_key": "The authkey must be 32 hex characters"},
        "abort": {"already_configured": "Device is already configured"},
        "entity": {"outlet": "{label}", "power": "{label} power", "energy": "{label} energy", "current": "{label} current",
                   "voltage": "{label} voltage", "power_factor": "{label} power factor", "energy_last_month": "{label} energy last month",
                   "total_power": "Total power", "ip_address": "IP address"},
    },
    "de": {
        "menu": {"title": "mFi-Gerät hinzufügen", "description": "Home Assistant übernimmt die Rolle des Ubiquiti mFi Controllers.",
                 "ssh": "Automatisch (SSH-Login des Geräts)", "manual": "Manuell (MAC-Adresse + Authkey)"},
        "ssh": {"title": "Per SSH übernehmen",
                "description": "Home Assistant meldet sich einmalig per SSH am Gerät an, liest den Schlüssel aus und stellt die Inform-URL auf diesen Server um. Eine Sicherung der alten Einstellung bleibt auf dem Gerät.",
                "host": "IP / Host des Geräts", "username": "SSH-Benutzer", "password": "SSH-Passwort",
                "inform_host": "Adresse von Home Assistant (aus Sicht des Geräts)", "inform_port": "Inform-Port (TCP)",
                "stun_port": "STUN-/Weckruf-Port (UDP)", "keep_key": "Vorhandenen Schlüssel behalten (alter Controller funktioniert nach Zurückstellen der URL weiter)"},
        "manual": {"title": "Manuelle Einrichtung",
                   "description": "Stelle das Gerät selbst auf `http://HA_IP:PORT/inform` um (z. B. per SSH: `mca-ctrl -t connect -s URL -k AUTHKEY`, siehe README). Home Assistant wartet auf die erste Meldung.",
                   "mac": "MAC-Adresse (wie im Inform-Header)", "authkey": "Authkey (32 Hex-Zeichen)",
                   "inform_port": "Inform-Port (TCP)", "stun_port": "STUN-/Weckruf-Port (UDP)"},
        "progress": {"provision": "Gerät wird eingerichtet, warte auf die erste Meldung (bis zu 90 s) ...",
                     "wait": "Warte auf die erste Meldung des Geräts (bis zu 90 s) ..."},
        "error": {"cannot_connect": "SSH-Verbindung fehlgeschlagen", "invalid_auth": "SSH-Anmeldung abgelehnt",
                  "provision_failed": "Einrichtung am Gerät fehlgeschlagen, siehe Log", "port_in_use": "Inform-/STUN-Port ist bereits belegt",
                  "no_inform": "Das Gerät hat sich nicht innerhalb von 90 s gemeldet", "invalid_mac": "Ungültige MAC-Adresse", "invalid_key": "Der Authkey muss aus 32 Hex-Zeichen bestehen"},
        "abort": {"already_configured": "Gerät ist bereits eingerichtet"},
        "entity": {"outlet": "{label}", "power": "{label} Leistung", "energy": "{label} Energie", "current": "{label} Strom",
                   "voltage": "{label} Spannung", "power_factor": "{label} Leistungsfaktor", "energy_last_month": "{label} Energie Vormonat",
                   "total_power": "Gesamtleistung", "ip_address": "IP-Adresse"},
    },
}


def build(t: dict) -> dict:
    sensors = {k: {"name": v} for k, v in t["entity"].items() if k != "outlet"}
    return {
        "config": {
            "step": {
                "user": {"title": t["menu"]["title"], "description": t["menu"]["description"],
                         "menu_options": {"ssh": t["menu"]["ssh"], "manual": t["menu"]["manual"]}},
                "ssh": {"title": t["ssh"]["title"], "description": t["ssh"]["description"],
                        "data": {k: t["ssh"][k] for k in ("host", "username", "password", "inform_host", "inform_port", "stun_port", "keep_key")}},
                "manual": {"title": t["manual"]["title"], "description": t["manual"]["description"],
                           "data": {k: t["manual"][k] for k in ("mac", "authkey", "inform_port", "stun_port")}},
            },
            "progress": t["progress"],
            "error": t["error"],
            "abort": t["abort"],
        },
        "entity": {"switch": {"outlet": {"name": t["entity"]["outlet"]}}, "sensor": sensors},
    }


(BASE / "translations").mkdir(exist_ok=True)
for lang, t in T.items():
    (BASE / "translations" / f"{lang}.json").write_text(json.dumps(build(t), indent=2, ensure_ascii=False) + "\n")
(BASE / "strings.json").write_text(json.dumps(build(T["en"]), indent=2, ensure_ascii=False) + "\n")
print("ok")

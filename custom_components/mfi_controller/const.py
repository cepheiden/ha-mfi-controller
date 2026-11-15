"""Constants for the mFi Controller integration."""

from __future__ import annotations

DOMAIN = "mfi_controller"

CONF_AUTHKEY = "authkey"
CONF_MAC = "mac"
CONF_INFORM_HOST = "inform_host"
CONF_INFORM_PORT = "inform_port"
CONF_STUN_PORT = "stun_port"
CONF_KEEP_KEY = "keep_key"
CONF_LABELS = "labels"
CONF_MODEL = "model"
CONF_PORT_COUNT = "port_count"

DEFAULT_INFORM_PORT = 6080
DEFAULT_STUN_PORT = 3478
DEFAULT_USERNAME = "ubnt"
INFORM_INTERVAL = 10  # seconds, sent to the device in every noop reply
FIRST_INFORM_TIMEOUT = 90  # seconds to wait for the device after provisioning

DATA_HUB = "hub"

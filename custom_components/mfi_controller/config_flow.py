"""Config flow: adopt an mFi device via SSH (automatic) or manually with MAC + authkey."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

from . import async_get_hub
from .const import (
    CONF_AUTHKEY,
    CONF_INFORM_HOST,
    CONF_INFORM_PORT,
    CONF_KEEP_KEY,
    CONF_LABELS,
    CONF_MAC,
    CONF_MODEL,
    CONF_PORT_COUNT,
    CONF_STUN_PORT,
    DEFAULT_INFORM_PORT,
    DEFAULT_STUN_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
    FIRST_INFORM_TIMEOUT,
    INFORM_INTERVAL,
)
from .protocol import new_authkey, normalize_key, normalize_mac
from .ssh import (
    DeviceIdentity,
    ProvisionAuthError,
    ProvisionError,
    async_provision,
    async_read_identity,
)

_LOGGER = logging.getLogger(__name__)


class MFiControllerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._input: dict[str, Any] = {}
        self._identity: DeviceIdentity | None = None
        self._key: str | None = None
        self._mac: str | None = None
        self._task: asyncio.Task | None = None
        self._error: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["ssh", "manual"])

    # ------------------------------------------------------------------ SSH (automatic)
    async def async_step_ssh(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._error:
            errors["base"], self._error = self._error, None
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                identity = await async_read_identity(host, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            except ProvisionAuthError:
                errors["base"] = "invalid_auth"
            except ProvisionError as err:
                _LOGGER.debug("SSH to %s failed: %s", host, err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(identity.mac)
                self._abort_if_unique_id_configured()
                self._input = {**user_input, CONF_HOST: host}
                self._identity = identity
                self._mac = identity.mac
                keep = user_input.get(CONF_KEEP_KEY, True)
                self._key = identity.authkey if (keep and identity.authkey and not identity.is_default) else new_authkey()
                self._task = None
                return await self.async_step_provision()

        defaults = self._input or user_input or {}
        source_ip = defaults.get(CONF_INFORM_HOST)
        if not source_ip:
            try:
                source_ip = await async_get_source_ip(self.hass)
            except Exception:  # noqa: BLE001
                source_ip = ""
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_INFORM_HOST, default=source_ip): str,
            vol.Required(CONF_INFORM_PORT, default=defaults.get(CONF_INFORM_PORT, DEFAULT_INFORM_PORT)): vol.Coerce(int),
            vol.Required(CONF_STUN_PORT, default=defaults.get(CONF_STUN_PORT, DEFAULT_STUN_PORT)): vol.Coerce(int),
            vol.Required(CONF_KEEP_KEY, default=defaults.get(CONF_KEEP_KEY, True)): bool,
        })
        return self.async_show_form(step_id="ssh", data_schema=schema, errors=errors)

    async def async_step_provision(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._task is None:
            self._task = self.hass.async_create_task(self._provision_and_wait())
        if not self._task.done():
            return self.async_show_progress(step_id="provision", progress_action="provision", progress_task=self._task)
        try:
            self._task.result()
        except ProvisionAuthError:
            self._error = "invalid_auth"
        except ProvisionError as err:
            _LOGGER.warning("Provisioning mFi device failed: %s", err)
            self._error = "provision_failed"
        except TimeoutError:  # before OSError: TimeoutError is a subclass of it
            self._error = "no_inform"
        except OSError as err:
            _LOGGER.warning("Cannot open the inform port: %s", err)
            self._error = "port_in_use"
        if self._error:
            self._task = None
            return self.async_show_progress_done(next_step_id="ssh")
        return self.async_show_progress_done(next_step_id="finish")

    async def _provision_and_wait(self) -> None:
        assert self._identity and self._key and self._mac
        hub = await async_get_hub(self.hass, self._input[CONF_INFORM_PORT], self._input[CONF_STUN_PORT])
        device = hub.register(self._mac, self._key, INFORM_INTERVAL)
        try:
            url = f"http://{self._input[CONF_INFORM_HOST]}:{hub.inform_port}/inform"
            await async_provision(self._input[CONF_HOST], self._input[CONF_USERNAME], self._input[CONF_PASSWORD], url, self._key)
            await device.wait_first_inform(FIRST_INFORM_TIMEOUT)
        except BaseException:
            hub.unregister(self._mac)
            raise

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._mac and self._key
        hub = await async_get_hub(self.hass, self._input[CONF_INFORM_PORT], self._input[CONF_STUN_PORT])
        device = hub.devices.get(self._mac)
        ident = self._identity
        labels = {str(k): v for k, v in (ident.labels if ident else {}).items()}
        port_count = (ident.port_count if ident else 0) or (len(device.ports) if device else 0)
        name = (device.info.model_display if device and device.info else None) or "mFi"
        host = self._input.get(CONF_HOST) or (device.info.ip if device and device.info else self._mac)
        return self.async_create_entry(
            title=f"{name} ({host})",
            data={
                CONF_MAC: self._mac,
                CONF_AUTHKEY: self._key,
                CONF_HOST: host,
                CONF_INFORM_PORT: self._input[CONF_INFORM_PORT],
                CONF_STUN_PORT: self._input[CONF_STUN_PORT],
                CONF_MODEL: (ident.model if ident else None) or (device.info.model if device and device.info else None),
                CONF_PORT_COUNT: port_count,
                CONF_LABELS: labels,
            },
        )

    # ------------------------------------------------------------------ manual
    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._error:
            errors["base"], self._error = self._error, None
        if user_input is not None:
            try:
                mac = normalize_mac(user_input[CONF_MAC])
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"
            try:
                key = normalize_key(user_input[CONF_AUTHKEY])
            except ValueError:
                errors[CONF_AUTHKEY] = "invalid_key"
            if not errors:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                self._input = dict(user_input)
                self._mac, self._key, self._identity, self._task = mac, key, None, None
                return await self.async_step_wait()
        defaults = self._input or {}
        schema = vol.Schema({
            vol.Required(CONF_MAC, default=defaults.get(CONF_MAC, "")): str,
            vol.Required(CONF_AUTHKEY): str,
            vol.Required(CONF_INFORM_PORT, default=defaults.get(CONF_INFORM_PORT, DEFAULT_INFORM_PORT)): vol.Coerce(int),
            vol.Required(CONF_STUN_PORT, default=defaults.get(CONF_STUN_PORT, DEFAULT_STUN_PORT)): vol.Coerce(int),
        })
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    async def async_step_wait(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._task is None:
            self._task = self.hass.async_create_task(self._wait_only())
        if not self._task.done():
            return self.async_show_progress(step_id="wait", progress_action="wait", progress_task=self._task)
        try:
            self._task.result()
        except TimeoutError:
            self._error = "no_inform"
        except OSError:
            self._error = "port_in_use"
        if self._error:
            self._task = None
            return self.async_show_progress_done(next_step_id="manual")
        return self.async_show_progress_done(next_step_id="finish")

    async def _wait_only(self) -> None:
        assert self._mac and self._key
        hub = await async_get_hub(self.hass, self._input[CONF_INFORM_PORT], self._input[CONF_STUN_PORT])
        device = hub.register(self._mac, self._key, INFORM_INTERVAL)
        try:
            await device.wait_first_inform(FIRST_INFORM_TIMEOUT)
        except BaseException:
            hub.unregister(self._mac)
            raise

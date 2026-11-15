"""End-to-end tests against the simulated device."""

import asyncio
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mfi_controller.const import DOMAIN
from custom_components.mfi_controller.ssh import DeviceIdentity

from .conftest import KEY, MAC
from .device_sim import SimDevice


def _entry(ports, **extra):
    data = {"mac": MAC, "authkey": KEY, "host": "127.0.0.1", "inform_port": ports[0], "stun_port": ports[1],
            "model": "P3E", "port_count": 3, "labels": {"1": "TV", "2": "p2"}}
    data.update(extra)
    return MockConfigEntry(domain=DOMAIN, title="mPower (127.0.0.1)", unique_id=MAC, data=data)


async def _wait(predicate, timeout=5.0):
    for _ in range(int(timeout / 0.05)):
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


async def test_push_switch_and_availability(hass, ports):
    entry = _entry(ports)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent = er.async_get(hass)
    ids = sorted(e.entity_id for e in er.async_entries_for_config_entry(ent, entry.entry_id))
    assert "switch.mpower_tv" in ids and "sensor.mpower_tv_power" in ids and "sensor.mpower_total_power" in ids
    assert hass.states.get("switch.mpower_tv").state == STATE_UNAVAILABLE  # nothing received yet

    sim = SimDevice(MAC, KEY, ports[0])
    await sim.start()
    try:
        assert await _wait(lambda: hass.states.get("switch.mpower_tv").state == STATE_ON)
        s = hass.states.get
        assert float(s("sensor.mpower_tv_power").state) == 10.0
        assert float(s("sensor.mpower_p2_power").state) == 20.0
        assert float(s("sensor.mpower_tv_energy").state) == 1.5
        assert s("sensor.mpower_tv_energy").attributes["state_class"] == "total_increasing"
        assert float(s("sensor.mpower_tv_power_factor").state) == 50.0
        assert float(s("sensor.mpower_total_power").state) == 60.0
        assert s("sensor.mpower_ip_address").state == "127.0.0.1"
        assert s("sensor.mpower_tv_energy_last_month") is None  # disabled by default

        # switching must work although the device only informs every 30 s -> wake-up over UDP
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.mpower_p2"}, blocking=True)
        assert loop.time() - t0 < 3
        assert sim.outputs[2] is False and sim.wakeups >= 1
        assert sim.commands[-1]["port"] == 2 and sim.commands[-1]["val"] == 0 and sim.commands[-1]["sId"] == "sid2"
        assert s("switch.mpower_p2").state == STATE_OFF
        assert float(s("sensor.mpower_p2_power").state) == 0.0
        await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.mpower_p2"}, blocking=True)
        assert sim.outputs[2] is True and s("switch.mpower_p2").state == STATE_ON

        # device disappears -> unavailable
        await sim.stop()
        device = entry.runtime_data.device
        device.last_inform -= 3600
        device._notify()
        await hass.async_block_till_done()
        assert s("switch.mpower_p2").state == STATE_UNAVAILABLE
    finally:
        await sim.stop()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_switch_fails_when_offline(hass, ports):
    entry = _entry(ports)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sim = SimDevice(MAC, KEY, ports[0])
    await sim.start(run_loop=False)
    await sim.inform()
    await sim.stop()  # no more wake-up listener
    await hass.async_block_till_done()
    device = entry.runtime_data.device
    with patch("custom_components.mfi_controller.hub.COMMAND_DELIVERY_TIMEOUT", 1.0), \
         patch("custom_components.mfi_controller.hub.WAKEUP_RETRY", 0.2):
        from custom_components.mfi_controller.hub import CommandError
        try:
            await device.async_set_output(1, False)
        except CommandError:
            pass
        else:
            raise AssertionError("expected CommandError")
    assert device._pending == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_wrong_key_and_unknown_device_ignored(hass, ports):
    entry = _entry(ports)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    import aiohttp
    for sim in (SimDevice(MAC, "ff" * 16, ports[0]), SimDevice("24:a4:3c:99:99:99", KEY, ports[0])):
        await sim.start(run_loop=False)
        try:
            await sim.inform()
        except aiohttp.ClientResponseError as err:
            assert err.status in (403, 404)
        else:
            raise AssertionError("inform must be rejected")
        finally:
            await sim.stop()
    assert entry.runtime_data.device.last_inform is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow_ssh(hass, ports):
    sims = []

    identity = DeviceIdentity(mac=MAC, model="P3E", port_count=3, authkey=KEY, is_default=False,
                              inform_url="http://old:6080/inform", labels={1: "TV"})

    async def fake_provision(host, username, password, url, key):
        assert url == f"http://192.0.2.10:{ports[0]}/inform" and key == KEY
        sim = SimDevice(MAC, key, ports[0])
        await sim.start()
        sims.append(sim)
        return identity

    with patch("custom_components.mfi_controller.config_flow.async_read_identity", return_value=identity), \
         patch("custom_components.mfi_controller.config_flow.async_provision", side_effect=fake_provision):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] is FlowResultType.MENU
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "ssh"})
        assert result["type"] is FlowResultType.FORM and result["step_id"] == "ssh"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "host": "192.168.1.50", "username": "ubnt", "password": "pw", "inform_host": "192.0.2.10",
            "inform_port": ports[0], "stun_port": ports[1], "keep_key": True,
        })
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        flow_id = result["flow_id"]
        assert await _wait(lambda: bool(sims) and sims[0].informs > 0)
        await hass.async_block_till_done()
        if not hass.config_entries.async_entries(DOMAIN):
            result = await hass.config_entries.flow.async_configure(flow_id)
            assert result["type"] is FlowResultType.CREATE_ENTRY, result
    try:
        entries = hass.config_entries.async_entries(DOMAIN)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.unique_id == MAC and entry.data["authkey"] == KEY and entry.data["labels"] == {"1": "TV"}
        assert entry.title == "mPower (192.168.1.50)"
        await hass.async_block_till_done()
        assert await _wait(lambda: (st := hass.states.get("switch.mpower_tv")) is not None and st.state == STATE_ON)
    finally:
        for sim in sims:
            await sim.stop()
    assert await hass.config_entries.async_unload(entries[0].entry_id)


async def test_config_flow_manual_timeout(hass, ports):
    with patch("custom_components.mfi_controller.config_flow.FIRST_INFORM_TIMEOUT", 0.5):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "manual"})
        bad = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "mac": "nope", "authkey": "short", "inform_port": ports[0], "stun_port": ports[1]})
        assert bad["errors"] == {"mac": "invalid_mac", "authkey": "invalid_key"}
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "mac": MAC.upper(), "authkey": KEY, "inform_port": ports[0], "stun_port": ports[1]})
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        flow_id = result["flow_id"]
        await asyncio.sleep(0.8)
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id)
        assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "no_inform"}
    hub = hass.data[DOMAIN]["hub"]
    assert MAC not in hub.devices
    await hub.stop()

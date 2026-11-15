"""Protocol tests; STUN bytes were captured from a real mFi controller 2.1.12."""

import pytest

from custom_components.mfi_controller import protocol as P

from .conftest import KEY, MAC


def test_roundtrip_and_header():
    obj = P.output_command(MAC, 2, "sid2", True)
    raw = P.encode_packet(MAC, KEY, obj)
    pkt = P.InformPacket.parse(raw)
    assert raw[:4] == b"TNBU" and pkt.mac == MAC and pkt.flags == P.FLAG_ENCRYPTED and pkt.data_version == 1
    back = pkt.decrypt(KEY)
    assert back["cmd"] == "mfi-output" and back["port"] == 2 and back["val"] == 1 and back["sId"] == "sid2"


def test_wrong_key_rejected():
    raw = P.encode_packet(MAC, KEY, P.noop_response(10))
    with pytest.raises(P.InformError):
        P.InformPacket.parse(raw).decrypt(P.MASTER_KEY)


def test_bad_packets():
    with pytest.raises(P.InformError):
        P.InformPacket.parse(b"nope")
    with pytest.raises(P.InformError):
        P.InformPacket.parse(b"XXXX" + bytes(36))


def test_parse_ports():
    payload = {"alarm": [
        {"sId": "a", "index": "vpower1", "entries": [
            {"tag": "output", "val": 1}, {"tag": "active_pwr", "val": 7.09}, {"tag": "i_rms", "val": 0.11},
            {"tag": "v_rms", "val": 231.7}, {"tag": "pf", "val": 0.26}, {"tag": "thismonth", "val": 2.78},
            {"tag": "lastmonth", "val": 5.45}, {"tag": "energy_sum", "val": 0.9375}]},
        {"sId": "b", "index": "vpower2", "entries": [{"tag": "output", "val": 0}]},
        {"sId": "c", "index": "something", "entries": []},
    ]}
    ports = P.parse_ports(payload)
    assert set(ports) == {1, 2}
    assert ports[1].output is True and ports[1].power == 7.09 and ports[1].energy_this_month == 2.78
    assert ports[1].sensor_id == "a" and ports[2].output is False and ports[2].power is None


def test_stun_matches_real_controller():
    request = bytes.fromhex("00010008000000000000000000000000000000000003000400000000")
    expected = bytes.fromhex(
        "0101002400000000000000000000000000000000000100080001aa3cc0a86fac"
        "0004000800010d96000000000005000800010d9600000000"
    )
    assert P.stun_response(request, ("192.168.111.172", 43580), 3478) == expected
    assert P.stun_response(b"\x88\x88" + bytes(18), ("1.2.3.4", 1), 3478) is None


def test_normalizers():
    assert P.normalize_mac("24A43C86613B") == "24:a4:3c:86:61:3b"
    assert P.normalize_key(KEY.upper()) == KEY
    with pytest.raises(ValueError):
        P.normalize_key("xyz")
    assert len(P.new_authkey()) == 32

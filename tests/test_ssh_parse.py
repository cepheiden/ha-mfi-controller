"""ssh.py parsing (no network)."""

from custom_components.mfi_controller.ssh import parse_identity

BOARD = '''<?
$board_name="mPower";
$board_shortname="P3E";
$board_hwaddr="24A43C86613B";
$feature_power=3;
>'''
MGMT = """mgmt.is_default=false
mgmt.authkey=00112233445566778899AABBCCDDEEFF
mgmt.servers.1.url=http://192.168.1.2:6080/inform
"""
CONFIG = "port.0.label=P1\nport.1.label=p2\nport.2.model=Outlet\n"


def test_parse_identity():
    ident = parse_identity(BOARD, MGMT, CONFIG)
    assert ident.mac == "24:a4:3c:86:61:3b"
    assert ident.model == "P3E" and ident.port_count == 3
    assert ident.authkey == "00112233445566778899aabbccddeeff" and ident.is_default is False
    assert ident.labels == {1: "P1", 2: "p2"}
    assert ident.inform_url.endswith(":6080/inform")


def test_default_device():
    ident = parse_identity(BOARD, "mgmt.is_default=true\n", "")
    assert ident.authkey is None and ident.is_default is True and ident.labels == {}

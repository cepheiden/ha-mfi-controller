"""Shared fixtures."""

import socket

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]

MAC = "24:a4:3c:00:00:01"
KEY = "00112233445566778899aabbccddeeff"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def free_port(kind=socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ports(socket_enabled):
    return free_port(), free_port(socket.SOCK_DGRAM)

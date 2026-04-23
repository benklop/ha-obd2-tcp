"""Unit tests for python-OBD wrapper.

These tests validate integration with the *real* `obd` package API while
mocking out the actual transport / adapter I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Allow importing custom component modules directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

import obd  # noqa: E402


class _FakeResponse:
    def __init__(self, *, messages=None, value=None, is_null=False) -> None:
        self.messages = messages or []
        self.value = value
        self._is_null = is_null

    def is_null(self) -> bool:
        return self._is_null


class _FakeMessage:
    def __init__(self, raw: str) -> None:
        self._raw = raw

    def raw(self) -> str:
        return self._raw


class _FakeELM:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send_and_parse(self, cmd: bytes) -> list:
        self.sent.append(cmd)
        return []


class _FakeOBD:
    """Fake `obd.OBD` instance used to intercept calls from our wrapper."""

    def __init__(self, portstr=None, baudrate=None, protocol=None, fast=True, timeout=0.1, check_voltage=True, start_low_power=False):  # noqa: E501
        # Mode 01 / DTC tests expect an ECU link (see _car_connected in obd_client).
        self._status = obd.OBDStatus.CAR_CONNECTED
        self._portstr = portstr
        self._fast = fast
        self._timeout = timeout
        self._check_voltage = check_voltage
        self._query_handler = None
        self.interface = _FakeELM()

    def close(self) -> None:
        self._status = obd.OBDStatus.NOT_CONNECTED

    def status(self):
        return self._status

    def is_connected(self) -> bool:
        # python-OBD defines is_connected() == CAR_CONNECTED, but our wrapper
        # only uses it as a truthy "connected" check. Keep it simple here.
        return self._status != obd.OBDStatus.NOT_CONNECTED

    def query(self, cmd, force: bool = False):
        assert force is True
        if self._query_handler is None:
            return _FakeResponse(is_null=True)
        return self._query_handler(cmd)


def test_portstr_socket_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from obd2_tcp.obd_client import PythonOBDClient  # noqa: E402

    c = PythonOBDClient("192.168.1.50", 35000)
    assert c.portstr == "socket://192.168.1.50:35000"


def test_request_mode01_extracts_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from obd2_tcp.obd_client import PythonOBDClient  # noqa: E402

    monkeypatch.setattr(obd, "OBD", _FakeOBD)

    c = PythonOBDClient("1.2.3.4", 35000)
    c.connect()

    # wire query handler
    assert c._conn is not None  # noqa: SLF001
    c._conn._query_handler = lambda cmd: _FakeResponse(  # noqa: SLF001
        messages=[
            # includes spaces/newlines/headers — parser should still find 41 0C and bytes
            _FakeMessage("7E8 03 41 0C 1A F8\r"),
            _FakeMessage(">"),
        ],
        value=None,
        is_null=False,
    )

    res = c.request_mode01(0x0C)
    assert res.ok is True
    assert res.payload_hex.startswith("1AF8")
    assert res.data_bytes[:2] == [0x1A, 0xF8]

    # Ensure command object is cached per pid
    res2 = c.request_mode01(0x0C)
    assert res2.data_bytes[:2] == [0x1A, 0xF8]
    assert 0x0C in c._cmd_cache  # noqa: SLF001
    assert isinstance(c._cmd_cache[0x0C], obd.OBDCommand)  # noqa: SLF001


def test_request_mode01_non_callable_raw_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed python-OBD messages (raw=None) must not raise — vehicle-off ECU quirks."""
    from obd2_tcp.obd_client import PythonOBDClient  # noqa: E402

    class _BadMessage:
        raw = None  # noqa: A003  # intentional: elicits NoneType is not callable if mishandled

    monkeypatch.setattr(obd, "OBD", _FakeOBD)

    c = PythonOBDClient("1.2.3.4", 35000)
    c.connect()
    assert c._conn is not None  # noqa: SLF001
    c._conn._query_handler = lambda cmd: _FakeResponse(  # noqa: SLF001
        messages=[_BadMessage(), _FakeMessage("41 0C 1A F8")],
        value=None,
        is_null=False,
    )

    res = c.request_mode01(0x0C)
    assert res.ok is True
    assert res.data_bytes[:2] == [0x1A, 0xF8]


@pytest.mark.parametrize("raw", ["NO DATA", "UNABLE TO CONNECT", "BUS INIT: ERROR"])
def test_request_mode01_no_data_handling(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    from obd2_tcp.obd_client import PythonOBDClient  # noqa: E402

    monkeypatch.setattr(obd, "OBD", _FakeOBD)

    c = PythonOBDClient("1.2.3.4", 35000)
    c.connect()
    assert c._conn is not None  # noqa: SLF001
    c._conn._query_handler = lambda cmd: _FakeResponse(  # noqa: SLF001
        messages=[_FakeMessage(raw)],
        value=None,
        is_null=False,
    )

    res = c.request_mode01(0x0D)
    assert res.ok is False
    assert res.data_bytes == []


def test_read_adapter_voltage_magnitude(monkeypatch: pytest.MonkeyPatch) -> None:
    from obd2_tcp.obd_client import PythonOBDClient  # noqa: E402

    monkeypatch.setattr(obd, "OBD", _FakeOBD)

    class _Qty:
        def __init__(self, magnitude: float) -> None:
            self.magnitude = magnitude

    c = PythonOBDClient("1.2.3.4", 35000)
    c.connect()
    assert c._conn is not None  # noqa: SLF001
    c._conn._query_handler = lambda cmd: _FakeResponse(  # noqa: SLF001
        messages=[_FakeMessage("OK")],
        value=_Qty(12.6),
        is_null=False,
    )

    from obd2_tcp.const import DEFAULT_ADAPTER_AT_RV_VOLTAGE_OFFSET_V

    v = c.read_adapter_voltage()
    assert v == pytest.approx(12.6 + DEFAULT_ADAPTER_AT_RV_VOLTAGE_OFFSET_V)


def test_read_adapter_voltage_zero_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    from obd2_tcp.obd_client import PythonOBDClient  # noqa: E402

    monkeypatch.setattr(obd, "OBD", _FakeOBD)

    class _Qty:
        def __init__(self, magnitude: float) -> None:
            self.magnitude = magnitude

    c = PythonOBDClient("1.2.3.4", 35000, adapter_rv_offset_v=0.0)
    c.connect()
    assert c._conn is not None  # noqa: SLF001
    c._conn._query_handler = lambda cmd: _FakeResponse(  # noqa: SLF001
        messages=[_FakeMessage("OK")],
        value=_Qty(12.4),
        is_null=False,
    )

    v = c.read_adapter_voltage()
    assert v == pytest.approx(12.4)


def test_disable_elm_low_power_sends_pp_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    from obd2_tcp.obd_client import PythonOBDClient  # noqa: E402

    monkeypatch.setattr(obd, "OBD", _FakeOBD)

    c = PythonOBDClient("1.2.3.4", 35000, disable_elm_low_power=True)
    c.connect()
    assert c._conn is not None  # noqa: SLF001
    assert c._conn.interface.sent == [b"ATPP0ESV7A", b"ATPP0EON"]  # noqa: SLF001


def test_quick_probe_does_not_send_pp_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    from obd2_tcp.obd_client import PythonOBDClient  # noqa: E402

    last: dict[str, _FakeOBD] = {}

    class _RecordingFakeOBD(_FakeOBD):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            last["obd"] = self

    monkeypatch.setattr(obd, "OBD", _RecordingFakeOBD)

    c = PythonOBDClient("1.2.3.4", 35000, disable_elm_low_power=True)
    assert c.quick_probe() is True
    assert last["obd"].interface.sent == []


def test_fetch_dtcs_parses_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    from obd2_tcp.obd_client import PythonOBDClient  # noqa: E402

    monkeypatch.setattr(obd, "OBD", _FakeOBD)

    c = PythonOBDClient("1.2.3.4", 35000)
    c.connect()
    assert c._conn is not None  # noqa: SLF001
    c._conn._query_handler = lambda cmd: _FakeResponse(  # noqa: SLF001
        messages=[_FakeMessage("43 ...")],
        value=[("P0620", "Generator Control Circuit"), ("U0123", None), ("", "bad")],
        is_null=False,
    )

    codes = c.fetch_dtcs()
    assert codes == ["P0620", "U0123"]


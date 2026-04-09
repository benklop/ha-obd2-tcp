"""Async TCP connection to ELM327 with serialized access."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Final

from .const import ELM_PROMPT, ELM_READ_CHUNK, ELM_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_CR: Final = re.compile(rb"\r")


class ELMConnectionError(Exception):
    """Connection or protocol failure."""


class ELMConnection:
    def __init__(self, host: str, port: int, timeout: float = ELM_TIMEOUT) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> None:
        async with self._lock:
            await self._async_connect_unlocked()

    async def _async_connect_unlocked(self) -> None:
        await self.async_disconnect()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
        except (TimeoutError, OSError) as err:
            raise ELMConnectionError(f"TCP connect failed: {err}") from err

    async def async_disconnect(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        self._writer = None
        self._reader = None

    async def async_send_command(self, cmd: str, *, expect_prompt: bool = True) -> str:
        """Send command (CR appended), return full response text up to prompt."""
        async with self._lock:
            if not self.connected:
                await self._async_connect_unlocked()
            return await self._send_unlocked(cmd, expect_prompt=expect_prompt)

    async def _send_unlocked(self, cmd: str, *, expect_prompt: bool) -> str:
        if not self._reader or not self._writer:
            raise ELMConnectionError("Not connected")

        line = cmd if cmd.endswith("\r") else f"{cmd}\r"
        self._writer.write(line.encode("ascii", errors="ignore"))
        await self._writer.drain()

        if not expect_prompt:
            return ""

        return await self._read_until_prompt()

    async def _read_until_prompt(self) -> str:
        assert self._reader is not None
        buf = bytearray()
        deadline = asyncio.get_event_loop().time() + self.timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(ELM_READ_CHUNK),
                    timeout=min(2.0, self.timeout),
                )
            except TimeoutError:
                chunk = b""
            if not chunk:
                break
            buf.extend(chunk)
            if ELM_PROMPT in buf or buf.rstrip().endswith(b">"):
                break
        text = buf.decode("ascii", errors="replace")
        text = text.replace("\x00", "")
        return text

    def strip_echo(self, response: str, command: str) -> str:
        """Remove echoed command lines from ELM response."""
        lines = []
        cmd_clean = command.strip().upper()
        for line in response.splitlines():
            ln = line.strip()
            if not ln or ln == ">":
                continue
            if ln.upper() == cmd_clean:
                continue
            lines.append(line)
        return "\n".join(lines)

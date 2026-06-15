"""Manage isolated inference worker subprocesses."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..utils.logger import get_logger
from .protocol import WorkerRequest, encode_request, parse_response

logger = get_logger("workers.pool")


@dataclass
class WorkerClient:
    name: str
    module: str
    process: subprocess.Popen[str] | None = None
    _io_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return

        self.process = subprocess.Popen(
            [sys.executable, "-m", self.module],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        logger.info("Started %s worker (pid=%s)", self.name, self.process.pid)

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None

    def _call_sync(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError(f"{self.name}_worker_not_running")

        request = WorkerRequest(id=str(uuid4()), method=method, params=params)
        with self._io_lock:
            assert self.process.stdin is not None
            assert self.process.stdout is not None
            self.process.stdin.write(encode_request(request) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f"{self.name}_worker_closed")

        response = parse_response(line)
        if not response.ok:
            raise RuntimeError(response.error or f"{self.name}_worker_error")
        return response.result or {}

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._call_sync, method, params or {})


class WorkerPool:
    def __init__(self) -> None:
        self.tts = WorkerClient("tts", "comms_platform.workers.tts_worker")
        self.tti = WorkerClient("tti", "comms_platform.workers.tti_worker")
        self.tt3d = WorkerClient("tt3d", "comms_platform.workers.tt3d_worker")

    async def start(self) -> None:
        await asyncio.gather(
            asyncio.to_thread(self.tts.start),
            asyncio.to_thread(self.tti.start),
            asyncio.to_thread(self.tt3d.start),
        )
        await asyncio.gather(
            self.tts.call("ping"),
            self.tti.call("ping"),
            self.tt3d.call("ping"),
        )
        logger.info("Inference worker pool is ready.")

    async def stop(self) -> None:
        await asyncio.gather(
            asyncio.to_thread(self.tts.stop),
            asyncio.to_thread(self.tti.stop),
            asyncio.to_thread(self.tt3d.stop),
        )

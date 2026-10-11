"""Assemble a gateway from a Config: store, router, auth, app. Also a thread
runner used by tests and the demo."""

from __future__ import annotations

import logging
import socket
import threading
import time

import uvicorn

from .config import Config
from .routing.router import Router
from .security import Auth
from .server import build_app
from .store import Store


def build(cfg: Config, with_store: bool = True):
    store = Store(cfg.resolve(cfg.server.state_db)) if with_store else None
    router = Router(cfg, store)
    auth = Auth(cfg)
    app = build_app(cfg, router, auth, store)
    return app, router, auth, store


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # uvicorn access logs would contain paths only (never bodies), but keep them quiet by default.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def free_port(host: str = "127.0.0.1") -> int:
    s = socket.socket()
    s.bind((host, 0))
    p = s.getsockname()[1]
    s.close()
    return p


class GatewayThread:
    """Run the gateway in a background thread (real HTTP server, real sockets)."""

    def __init__(self, cfg: Config, with_store: bool = True) -> None:
        self.cfg = cfg
        self.app, self.router, self.auth, self.store = build(cfg, with_store)
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.cfg.server.host}:{self.cfg.server.port}"

    def start(self) -> str:
        config = uvicorn.Config(self.app, host=self.cfg.server.host, port=self.cfg.server.port, log_level="error")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            if self._server.started and self.app.state.gw.ready:
                return self.url
            time.sleep(0.02)
        raise RuntimeError("gateway did not start in time")

    def run(self, coro):  # type: ignore[no-untyped-def]
        """Run a coroutine on the gateway's event loop from another thread (adapters are loop-bound)."""
        import asyncio

        loop = self.app.state.gw.loop
        if loop is None:
            raise RuntimeError("gateway loop not running")
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=10)
        if self.store:
            self.store.close()

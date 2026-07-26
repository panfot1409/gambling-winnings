"""An independent heartbeat, because the trading loop is not a liveness signal.

Cockpit calls a bot offline once its last heartbeat is older than 90 seconds. This platform's loop
is bar-driven: a daily-bar run replayed at operator pace, or a run waiting on the next candle,
can legitimately spend far longer than 90 seconds between iterations, and a heartbeat emitted from
inside the loop would report a healthy trader as dead.

So liveness is tied to the *process*, not to the loop. One daemon thread beats on its own clock
while the process lives, and:

* it is started only after the trader has initialised, so a process that failed to start never
  claims to be alive;
* it is stopped explicitly at shutdown, and its thread is a daemon, so it can neither hold the
  process open nor outlive it;
* it never blocks the loop — the trading thread's only interaction with it is ``start`` and
  ``stop``, both of which return promptly;
* it never raises, and it survives a Cockpit outage: the client buffers and retries beneath it;
* starting twice is a no-op, so there is never a second beating thread.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from eth_research.cockpit.reporter import CockpitReporter

log = logging.getLogger("eth_research.cockpit")

#: How long ``stop`` waits for the worker to notice, before giving up and letting the daemon die.
DEFAULT_JOIN_TIMEOUT_SECONDS: float = 2.0


class HeartbeatWorker:
    """Beats once per interval for as long as the process is trading."""

    __slots__ = ("_beats", "_interval", "_lock", "_monotonic", "_reporter", "_stop", "_thread")

    def __init__(
        self,
        reporter: CockpitReporter,
        *,
        interval_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._reporter = reporter
        self._interval = max(0.001, float(interval_seconds))
        self._monotonic = monotonic
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._beats = 0

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def beats(self) -> int:
        """How many heartbeats have been emitted. Observability, not control."""
        return self._beats

    def start(self) -> None:
        """Start beating. Calling this again while it runs does nothing."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._beats = 0
            thread = threading.Thread(
                target=self._run, name="eth-research-cockpit-heartbeat", daemon=True
            )
            self._thread = thread
            thread.start()

    def stop(self, timeout: float = DEFAULT_JOIN_TIMEOUT_SECONDS) -> None:
        """Ask the worker to finish and wait a bounded moment for it."""
        with self._lock:
            thread = self._thread
            self._stop.set()
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            if thread is not None and not thread.is_alive():
                self._thread = None

    def __enter__(self) -> HeartbeatWorker:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def _run(self) -> None:
        started = self._monotonic()
        # Beat immediately: the operator should see the bot online the moment it starts, not one
        # interval later.
        self._beat(0)
        while not self._stop.wait(self._interval):
            self._beat(int(self._monotonic() - started))

    def _beat(self, uptime_seconds: int) -> None:
        try:
            self._reporter.heartbeat(uptime_seconds=uptime_seconds)
        except Exception as error:  # the reporter already swallows; this is the last net
            log.warning("heartbeat worker error: %s", error)
            return
        self._beats += 1


__all__ = ["DEFAULT_JOIN_TIMEOUT_SECONDS", "HeartbeatWorker"]

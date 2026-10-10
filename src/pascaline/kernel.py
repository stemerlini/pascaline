"""The kernel: the engine runs in its own process, like Jupyter's, so any
calculation can be interrupted and a runaway one never freezes the app."""

from __future__ import annotations

import os
import pickle
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from multiprocessing.connection import Connection

import sympy as sp

from .engine import Engine, Result


class Interrupted(Exception):
    """The kernel was stopped (cancelled, timed out or crashed) and restarted empty."""


@dataclass
class Reply:
    results: list[Result]
    names: dict[str, tuple[str, str]] = field(default_factory=dict)  # name → (signature, summary)


def summarize(engine: Engine) -> dict[str, tuple[str, str]]:
    out = {}
    for name in engine.user_names():
        value = engine.vars[name]
        if isinstance(value, sp.Lambda):
            out[name] = ("(" + ", ".join(map(str, value.variables)) + ")", "your function")
        else:
            try:
                text = sp.sstr(value)
            except ValueError:  # integers too long to print
                text = "a very big number"
            out[name] = ("", text[:60])
    return out


def _portable(res: Result) -> Result:
    """Results cross a process boundary; drop a value that can't be pickled."""
    try:
        pickle.dumps(res)
        return res
    except Exception:
        res.value = None
        return res


def _watch_parent() -> None:
    """Exit as soon as the app is gone, even in the middle of a long calculation."""
    parent = os.getppid()
    while True:
        time.sleep(1)
        if os.getppid() != parent:
            os._exit(0)


def _serve(conn, digits: int, degrees: bool) -> None:
    threading.Thread(target=_watch_parent, daemon=True).start()
    engine = Engine(digits=digits, degrees=degrees)
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        op = msg[0]
        if op == "run":  # ("run", src, cell, commit)
            results = [engine.run(msg[1], msg[2], commit=msg[3])]
        elif op == "run_all":  # ("run_all", [src, ...]): reset, then the whole sheet
            engine.reset()
            results = [engine.run(src, k + 1) for k, src in enumerate(msg[1])]
        elif op == "config":  # ("config", digits, degrees)
            engine.digits, engine.degrees = msg[1], msg[2]
            results = []
        else:
            results = []
        conn.send(Reply([_portable(r) for r in results], summarize(engine)))


class Kernel:
    """One engine process. Calls block the calling (worker) thread, never the UI."""

    def __init__(self, digits: int = 12, degrees: bool = False):
        self.digits, self.degrees = digits, degrees
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._start()

    def _start(self) -> None:
        # A plain subprocess on a socket pair: nothing of the app is re-imported,
        # and its output can never land on the TUI.
        ours, theirs = socket.socketpair()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "pascaline.kernel", str(theirs.fileno()), str(self.digits), str(int(self.degrees))],
            pass_fds=[theirs.fileno()],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # keyboard signals in the terminal never reach it
        )
        theirs.close()
        self.conn = Connection(ours.detach())

    def call(self, *msg, timeout: float | None = None) -> Reply:
        with self._lock:
            self._stop.clear()
            started = time.monotonic()
            try:
                self.conn.send(msg)
                while not self.conn.poll(0.03):
                    why = None
                    if self._stop.is_set():
                        why = "cancelled"
                    elif timeout and time.monotonic() - started > timeout:
                        why = f"stopped after {timeout:g} s"
                    elif self.proc.poll() is not None:
                        why = "the kernel crashed"
                    if why:
                        self._restart()
                        raise Interrupted(why)
                return self.conn.recv()
            except (EOFError, OSError):
                self._restart()
                raise Interrupted("the kernel crashed") from None

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def interrupt(self) -> None:
        """Stop whatever is running; the kernel comes back empty."""
        self._stop.set()

    def configure(self, digits: int, degrees: bool) -> None:
        self.digits, self.degrees = digits, degrees
        self.call("config", digits, degrees)

    def _restart(self) -> None:
        self.close()
        self._start()

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait(2)
        self.conn.close()


if __name__ == "__main__":
    # Import under the real module name, so replies unpickle as pascaline.kernel.Reply.
    from pascaline.kernel import _serve as serve

    serve(Connection(int(sys.argv[1])), int(sys.argv[2]), sys.argv[3] == "1")



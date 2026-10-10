import threading
import time

import pytest

from pascaline.kernel import Interrupted, Kernel


@pytest.fixture
def kernel():
    k = Kernel()
    yield k
    k.close()


def test_runs_and_keeps_state(kernel):
    kernel.call("run", "a = 2", 1, True)
    reply = kernel.call("run", "a^10", 2, True)
    assert reply.results[0].text == "1024"
    assert reply.names == {"a": ("", "2")}


def test_interrupt_stops_a_slow_calculation(kernel):
    errors = []

    def slow():
        try:
            kernel.call("run", "nextprime(10^4000)", 1, True)
        except Interrupted as exc:
            errors.append(exc)

    t = threading.Thread(target=slow)
    t.start()
    time.sleep(0.5)
    started = time.monotonic()
    kernel.interrupt()
    t.join(5)
    assert errors and time.monotonic() - started < 3
    assert kernel.call("run", "1+1", 1, True).results[0].text == "2"  # usable again, empty


def test_timeout(kernel):
    with pytest.raises(Interrupted, match="stopped after"):
        kernel.call("run", "nextprime(10^4000)", 1, False, timeout=0.5)

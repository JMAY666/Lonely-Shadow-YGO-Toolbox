"""Non-overlapping named scopes; nested native timings are reported separately."""
from contextlib import contextmanager
import time


@contextmanager
def measure(timings, name):
    began = time.perf_counter()
    try:
        yield
    finally:
        timings[name] = timings.get(name, 0.0) + time.perf_counter() - began

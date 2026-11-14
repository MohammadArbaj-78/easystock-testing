"""Tiny timing helper - diagnostics only.

Prints lines like "[PERF] imports done +820ms" to the server log
(Streamlit Cloud: Manage app -> Logs). Each Streamlit session runs in its
own thread, so the clock is kept per thread. It never raises, never
touches the UI, and does nothing but print.
"""

import sys
import threading
import time

_local = threading.local()


def perf_start(label: str = "run start") -> None:
    try:
        _local.t0 = time.perf_counter()
        print(f"[PERF] {label}", file=sys.stderr, flush=True)
    except Exception:
        pass


def perf_log(label: str) -> None:
    try:
        t0 = getattr(_local, "t0", None)
        if t0 is None:
            _local.t0 = t0 = time.perf_counter()
        ms = int((time.perf_counter() - t0) * 1000)
        print(f"[PERF] {label} +{ms}ms", file=sys.stderr, flush=True)
    except Exception:
        pass
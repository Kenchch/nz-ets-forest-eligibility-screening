"""Logging shared by every step.

Each module logs to a child of the "ets_screening" logger, and the scripts in
scripts/ log as ets_screening.<script>. Nothing is configured on import, so
pytest and the ArcGIS toolbox keep their own handlers; only a command-line
entry point calls command(). What ends up where:

    console                          INFO and above, without tracebacks (Python prints those)
    outputs/ets_screening.log        every scripts/ command, appended, with tracebacks
    <--output>/ets_screening.log     every ets-screen and ets-review-sample run, appended

Records carry their level, so `grep -E "WARNING|ERROR"` finds every warning,
rejected input and failed step. Python warnings (pandas, pyogrio, matplotlib)
are logged too, once capture_warnings() has run. Times are UTC.
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_NAME = "ets_screening.log"

log = logging.getLogger("ets_screening")
WARNINGS = logging.getLogger("py.warnings")  # where logging.captureWarnings sends them
LINE, DATE = "%(asctime)s  %(levelname)-7s  %(message)s", "%Y-%m-%dT%H:%M:%SZ"


def formatter(cls: type[logging.Formatter] = logging.Formatter) -> logging.Formatter:
    """LINE with UTC times."""
    f = cls(LINE, DATE)
    f.converter = time.gmtime
    return f


FORMAT = formatter()


def capture_warnings() -> None:
    """Send Python warnings through logging, so they reach the run log.

    Off, then on: logging only installs its hook when it has none saved, and a
    test framework that restores warnings.showwarning leaves a stale one.
    """
    logging.captureWarnings(False)
    logging.captureWarnings(True)


class _Brief(logging.Formatter):
    """Console lines without the traceback: Python prints it when the error is re-raised."""

    def format(self, record: logging.LogRecord) -> str:
        saved = record.exc_info, record.exc_text
        record.exc_info = record.exc_text = None
        try:
            return super().format(record)
        finally:
            record.exc_info, record.exc_text = saved


class _Console(logging.StreamHandler):
    """Writes to whatever sys.stderr is now, so it survives pytest swapping it per test."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, value):
        pass


def console() -> None:
    """Show the package's records on the console, once however often it is called."""
    if not any(isinstance(h, _Console) for h in log.handlers):
        h = _Console()
        h.setFormatter(formatter(_Brief))
        log.addHandler(h)
        WARNINGS.addHandler(h)


@contextmanager
def to_file(path: str | Path, logger: logging.Logger = log):
    """Append logger's records (and its children's) to path for the length of the block.

    The package logger brings Python warnings with it; a module's own logger does not.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(path, encoding="utf-8")
    h.setFormatter(FORMAT)
    loggers = [logger, WARNINGS] if logger is log else [logger]
    for lg in loggers:
        lg.addHandler(h)
    try:
        yield
    finally:
        for lg in loggers:
            lg.removeHandler(h)
        h.close()


@contextmanager
def step(name: str):
    """Log a step's start, end and time, or the error it stopped with."""
    t0 = time.perf_counter()
    log.info(f"{name}: start")
    try:
        yield
    except Exception as e:
        log.error(
            f"{name}: failed after {time.perf_counter() - t0:,.1f} s: {type(e).__name__}: {e}"
        )
        raise
    log.info(f"{name}: done in {time.perf_counter() - t0:,.1f} s")


@contextmanager
def command(name: str, path: str | Path):
    """Run a command-line entry point with logging set up and appended to path.

    The console shows INFO and above; the run log at path gets the same lines
    plus a crash's traceback. The block is logged like a step, under the
    command line it was started with. A SystemExit with an error status is
    logged as the run stopping rather than crashing; with status 0 it is done.
    """
    console()
    capture_warnings()
    log.setLevel(logging.INFO)
    with to_file(path):
        t0 = time.perf_counter()
        log.info(f"{name}: start: {' '.join([Path(sys.argv[0]).name, *sys.argv[1:]])}")
        try:
            yield
        except SystemExit as e:
            if e.code in (None, 0):
                log.info(f"{name}: done in {time.perf_counter() - t0:,.1f} s")
            else:
                detail = f"exit status {e.code}" if isinstance(e.code, int) else e.code
                log.error(f"{name}: stopped after {time.perf_counter() - t0:,.1f} s: {detail}")
            raise
        except Exception as e:
            log.error(
                f"{name}: failed after {time.perf_counter() - t0:,.1f} s: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            raise
        log.info(f"{name}: done in {time.perf_counter() - t0:,.1f} s")


def rel(path: str | Path) -> str:
    """path relative to the repository when inside it, so logs don't carry this machine's layout."""
    path = Path(path)
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)

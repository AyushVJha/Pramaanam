"""Retry a flaky network command with exponential backoff."""

import logging
import subprocess
import time

logger = logging.getLogger(__name__)


def run_with_retry(cmd: list[str], label: str, attempts: int = 5, base_wait: float = 10.0) -> None:
    """Run a subprocess, retrying on failure (e.g. internet down) with waits of 10, 20, 40...s.

    After `attempts` failures it raises and the program exits non-zero. The background
    service (scripts/install_ingest_service.sh) then restarts the whole job a few minutes
    later. Every step is safe to re-run, so work resumes where it stopped.
    """
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(cmd, check=True)
            return
        except (subprocess.CalledProcessError, OSError) as err:
            if attempt == attempts:
                raise
            wait = base_wait * 2 ** (attempt - 1)
            logger.warning(
                "%s failed (%s); retry %d/%d in %.0fs", label, err, attempt, attempts, wait
            )
            time.sleep(wait)

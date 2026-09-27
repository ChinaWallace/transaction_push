"""Short filesystem critical sections; network I/O never holds this lock."""
from contextlib import contextmanager
from pathlib import Path
import fcntl


@contextmanager
def snapshot_lock(directory, shared=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with (directory/"snapshot.lock").open("a") as handle:
        fcntl.flock(handle,fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)

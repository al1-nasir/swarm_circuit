"""One process, one bounded writer; ACK only after the future's commit completes."""

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import closing, contextmanager
from pathlib import Path
from queue import Full, Queue
from threading import Thread
from typing import Any, TypeVar, cast

T = TypeVar("T")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(path: Path, directory: Path | None = None) -> None:
    """Apply frozen migrations atomically, including the version marker."""
    directory = directory or Path(__file__).with_name("migrations")
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((directory / "manifest.json").read_text())
    with closing(connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        for file in sorted(directory.glob("[0-9]*.sql")):
            if hashlib.sha256(file.read_bytes()).hexdigest() != manifest[file.name]:
                raise RuntimeError(f"Migration checksum mismatch: {file.name}")
            version = file.name.split("_", 1)[0]
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if (
                exists
                and conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
                ).fetchone()
            ):
                continue
            # SQL literals here are fixed migration metadata, not user data.
            try:
                conn.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + file.read_text()
                    + f"\nINSERT INTO schema_migrations VALUES ('{version}',"
                    + f"'{file.name}',{now_ms()});\nCOMMIT;"
                )
            except BaseException:
                conn.rollback()
                raise


class WriterUnavailable(RuntimeError):
    """No durable success can be reported; retries must use stable keys."""


class Database:
    def __init__(self, path: Path, queue_size: int = 128, timeout: float = 5) -> None:
        self.path = path
        self.timeout = timeout
        self.queue: Queue[tuple[Callable[[sqlite3.Connection], Any], Future[Any]] | None] = Queue(
            maxsize=queue_size
        )
        self.closed = False
        self.thread = Thread(target=self._work, name="swarm-sqlite-writer", daemon=True)
        self.thread.start()

    def _work(self) -> None:
        conn = connect(self.path)
        try:
            while (job := self.queue.get()) is not None:
                fn, future = job
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    result = fn(conn)
                    conn.commit()
                except BaseException as exc:
                    conn.rollback()
                    future.set_exception(exc)
                else:
                    future.set_result(result)
        finally:
            conn.close()

    def write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        if self.closed or not self.thread.is_alive():
            raise WriterUnavailable("Writer unavailable")
        future: Future[Any] = Future()
        try:
            self.queue.put_nowait((fn, future))
        except Full as exc:
            raise WriterUnavailable("Writer queue full") from exc
        try:
            return cast(T, future.result(timeout=self.timeout))
        except TimeoutError as exc:
            raise WriterUnavailable("Commit outcome unknown; retry the same keys") from exc
        except sqlite3.OperationalError as exc:
            raise WriterUnavailable("Database write unavailable") from exc

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self.path)
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            yield conn
        finally:
            conn.rollback()
            conn.close()

    def close(self) -> None:
        self.closed = True
        self.queue.put(None)
        self.thread.join()

"""Subprocess ownership and status helpers."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from os import SEEK_END, PathLike
from subprocess import Popen
from tempfile import TemporaryFile
from typing import BinaryIO

ProcessCommand = str | Sequence[str]
WorkingDirectory = str | PathLike

# read_output() returns at most this many bytes from the end of each stream
OUTPUT_TAIL_BYTES = 1024 * 1024


class ProcessState(Enum):
    """Observable state of a managed process."""

    UNKNOWN = "unknown"
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(frozen=True)
class ProcessStatus:
    """Process state and exit code when the process has stopped.

    ``UNKNOWN`` means this runner has no successfully started process.
    """

    state: ProcessState
    exit_code: int | None = None


class ProcessLaunchError(OSError):
    """Raised when the operating system cannot start a requested process.

    It remains an ``OSError`` so callers that handled ``Popen`` launch failures
    continue to recognize the exception.
    """


class ProcessRunner:
    """Own one child process and expose its lifecycle without leaking Popen.

    A runner is intended for serialized calls from one owner; it is not
    thread-safe.

    Calls to ``terminate`` and ``kill`` are no-ops before a successful start
    and after the owned process exits. A successful start after exit replaces
    the previous process and its captured output; a rejected or failed start
    leaves the previous ownership unchanged.

    Captured output goes to two anonymous temporary files, not to pipes: the
    child never blocks on a full pipe buffer, however much it writes and
    whenever the owner reads. ``read_output`` returns the last
    ``OUTPUT_TAIL_BYTES`` of each stream; it never blocks and may be called
    again, also while the process runs. A process that outlives its owner
    keeps writing to its own file descriptors; the operating system removes
    the files once the last descriptor is closed.
    """

    def __init__(self) -> None:
        self._process: Popen | None = None
        self._capture_output = False
        self._stdout_file: BinaryIO | None = None
        self._stderr_file: BinaryIO | None = None

    def start(
        self,
        command: ProcessCommand,
        cwd: WorkingDirectory,
        capture_output: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Start a process, raising ProcessLaunchError if Popen fails."""

        if self.status().state is ProcessState.RUNNING:
            raise RuntimeError("a process is already running")

        stdout_file: BinaryIO | None = None
        stderr_file: BinaryIO | None = None
        try:
            if capture_output:
                # the runner owns both files beyond this call
                stdout_file = TemporaryFile()  # noqa: SIM115
                stderr_file = TemporaryFile()  # noqa: SIM115
                process = Popen(
                    command, cwd=cwd, stdout=stdout_file, stderr=stderr_file,
                    env=env,
                )
            else:
                process = Popen(command, cwd=cwd, env=env)
        except OSError as error:
            _close_files(stdout_file, stderr_file)
            raise ProcessLaunchError(
                f"could not start process {command!r}: {error}"
            ) from error
        _close_files(self._stdout_file, self._stderr_file)
        self._process = process
        self._capture_output = capture_output
        self._stdout_file = stdout_file
        self._stderr_file = stderr_file

    def status(self) -> ProcessStatus:
        """Poll the owned process; no process is represented as UNKNOWN."""

        if self._process is None:
            return ProcessStatus(ProcessState.UNKNOWN)

        exit_code = self._process.poll()
        if exit_code is None:
            return ProcessStatus(ProcessState.RUNNING)
        return ProcessStatus(ProcessState.STOPPED, exit_code)

    def terminate(self) -> None:
        """Send terminate to the owned process, if one has been started."""

        if self._process is not None:
            self._process.terminate()

    def kill(self) -> None:
        """Send kill to the owned process, if one has been started."""

        if self._process is not None:
            self._process.kill()

    def read_output(self) -> tuple[bytes, bytes]:
        """Return the end of the captured stdout and stderr.

        Each stream is cut to its last ``OUTPUT_TAIL_BYTES``. The call never
        blocks and can be repeated; while the process runs it returns what
        has been written so far.
        """

        if self._process is None or not self._capture_output:
            raise RuntimeError("no captured process output is available")
        stdout = self._stdout_file
        stderr = self._stderr_file
        if stdout is None or stderr is None:
            raise RuntimeError("captured process streams are unavailable")
        return _read_tail(stdout), _read_tail(stderr)


def _read_tail(stream: BinaryIO) -> bytes:
    """Read at most the last ``OUTPUT_TAIL_BYTES`` of a captured stream."""

    size = stream.seek(0, SEEK_END)
    stream.seek(max(0, size - OUTPUT_TAIL_BYTES))
    return stream.read()


def _close_files(*files: BinaryIO | None) -> None:
    """Close the capture files that were opened."""

    for file in files:
        if file is not None:
            file.close()

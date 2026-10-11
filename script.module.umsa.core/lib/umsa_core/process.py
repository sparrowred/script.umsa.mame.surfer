"""Subprocess ownership and status helpers."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from os import PathLike
from subprocess import PIPE, Popen
from typing import Union

ProcessCommand = Union[str, Sequence[str]]
WorkingDirectory = Union[str, PathLike]


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
    leaves the previous ownership unchanged. Captured streams are consumed by
    ``read_output`` and callers should wait for ``STOPPED`` before reading.
    """

    def __init__(self) -> None:
        self._process: Popen | None = None
        self._capture_output = False

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

        try:
            if capture_output:
                process = Popen(
                    command, cwd=cwd, stdout=PIPE, stderr=PIPE, env=env
                )
            else:
                process = Popen(command, cwd=cwd, env=env)
        except OSError as error:
            raise ProcessLaunchError(
                f"could not start process {command!r}: {error}"
            ) from error
        self._process = process
        self._capture_output = capture_output

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
        """Read captured stdout and stderr, preserving the existing order."""

        if self._process is None or not self._capture_output:
            raise RuntimeError("no captured process output is available")
        stdout = self._process.stdout
        stderr = self._process.stderr
        if stdout is None or stderr is None:
            raise RuntimeError("captured process streams are unavailable")
        return stdout.read(), stderr.read()

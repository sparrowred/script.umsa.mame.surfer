"""Start emulator processes and own one (:class:`ProcessRunner`)."""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from os import SEEK_END, PathLike
from subprocess import Popen
from tempfile import TemporaryFile
from typing import BinaryIO

ProcessCommand = str | Sequence[str]
WorkingDirectory = str | PathLike

# read_output() returns at most this many bytes from the end of each stream.
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


# ProcessLaunchError.reason: why a start failed (machine-readable).
LAUNCH_WORKING_DIR_MISSING = 'working_dir_missing'
LAUNCH_PROGRAM_MISSING = 'program_missing'
LAUNCH_PERMISSION_DENIED = 'permission_denied'
LAUNCH_FAILED = 'launch_failed'


class ProcessLaunchError(OSError):
    """Raised when the operating system cannot start a requested process.

    An ``OSError``, like the ``Popen`` failure it wraps. ``reason`` is one of
    the ``LAUNCH_*`` constants, ``path`` the path concerned (working directory
    or program), when known.
    """

    def __init__(self, message, reason=LAUNCH_FAILED, path=None):
        super().__init__(message)
        self.reason = reason
        self.path = path


def launch_popen(command: ProcessCommand, cwd: WorkingDirectory | None,
                 **popen_kwargs) -> Popen:
    """Start ``command`` with ``Popen``; the one place that starts emulators.

    A missing working directory is reported before anything is started.
    Every ``OSError`` of ``Popen`` becomes a ``ProcessLaunchError`` whose
    ``reason`` tells a missing working directory, a missing program and a
    missing permission apart.
    """

    if cwd and not os.path.isdir(cwd):
        raise ProcessLaunchError(
            f"could not start process {command!r}: working directory "
            f"{cwd!r} does not exist",
            LAUNCH_WORKING_DIR_MISSING, cwd)
    try:
        return Popen(command, cwd=cwd, **popen_kwargs)
    except OSError as error:
        if cwd is not None and error.filename == cwd:
            reason, path = LAUNCH_WORKING_DIR_MISSING, cwd
        elif isinstance(error, FileNotFoundError):
            reason, path = LAUNCH_PROGRAM_MISSING, _program(command)
        elif isinstance(error, PermissionError):
            reason, path = LAUNCH_PERMISSION_DENIED, _program(command)
        else:
            reason, path = LAUNCH_FAILED, None
        raise ProcessLaunchError(
            f"could not start process {command!r}: {error}", reason, path,
        ) from error


def _program(command: ProcessCommand):
    """Return the program of ``command`` (its first element)."""

    if isinstance(command, (str, bytes, PathLike)):
        return command
    return command[0] if command else None


class ProcessRunner:
    """Own one child process without exposing ``Popen``; not thread-safe.

    A successful start after exit replaces the previous process and its
    output; a failed start keeps the previous one. Captured output goes to
    anonymous temporary files, not pipes, so the child never blocks on a full
    pipe buffer; a process that outlives its owner keeps writing to them.
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
        """Start a process.

        Raises:
            RuntimeError: If the owned process still runs.
            ProcessLaunchError: If the process cannot start.
        """

        if self.status().state is ProcessState.RUNNING:
            raise RuntimeError("a process is already running")

        stdout_file: BinaryIO | None = None
        stderr_file: BinaryIO | None = None
        try:
            if capture_output:
                # The runner owns both files beyond this call.
                stdout_file = TemporaryFile()  # noqa: SIM115
                stderr_file = TemporaryFile()  # noqa: SIM115
                process = launch_popen(
                    command, cwd, stdout=stdout_file, stderr=stderr_file,
                    env=env,
                )
            else:
                process = launch_popen(command, cwd, env=env)
        except ProcessLaunchError:
            _close_files(stdout_file, stderr_file)
            raise
        except OSError as error:
            # The capture files could not be created.
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
        """Return the state of the owned process (``UNKNOWN`` without one)."""

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
        """Return the last ``OUTPUT_TAIL_BYTES`` of the captured stdout and stderr.

        Never blocks; while the process runs it returns what was written so
        far.
        """

        if self._process is None or not self._capture_output:
            raise RuntimeError("no captured process output is available")
        stdout = self._stdout_file
        stderr = self._stderr_file
        if stdout is None or stderr is None:
            raise RuntimeError("captured process streams are unavailable")
        return _read_tail(stdout), _read_tail(stderr)


def _read_tail(stream: BinaryIO) -> bytes:
    """Return at most the last ``OUTPUT_TAIL_BYTES`` of a captured stream."""

    size = stream.seek(0, SEEK_END)
    stream.seek(max(0, size - OUTPUT_TAIL_BYTES))
    return stream.read()


def _close_files(*files: BinaryIO | None) -> None:
    """Close the capture files that were opened."""

    for file in files:
        if file is not None:
            file.close()

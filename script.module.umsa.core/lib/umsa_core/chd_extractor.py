"""CHD extraction, cancellation and cleanup."""

import os
import re
import shutil
import subprocess

from umsa_core import log

from .abort import ShutdownRequested, resolve_wait
from .rom_cache import staged_dir

CHD_PROCESS_STOP_TIMEOUT = 2


class CHDExtractionCancelled(Exception):
    """Raised when the user cancels a running CHD extraction."""


class CHDExtractionError(RuntimeError):
    """Raised when chdman fails to extract a CHD."""


def _terminate_and_reap_process(process):
    """Stop a child process, escalating to kill if it ignores terminate."""
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=CHD_PROCESS_STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.wait()
    else:
        process.wait()


# launch files chdman writes for a CD image
LAUNCH_EXTENSIONS = ('.cue', '.gdi')
_PROGRESS = re.compile(r'(\d+(?:\.\d+)?)\s*%')


def parse_chdman_progress(text):
    """Last percentage of a chdman progress output, None without one."""

    found = _PROGRESS.findall(text)
    if not found:
        return None
    return min(100, int(float(found[-1])))


def _extracted_files(folder, launch_file):
    """Files of a finished extraction, the launch file first; [] without one."""

    names = sorted(os.listdir(folder))
    if launch_file in names:
        return [launch_file]
    launch = [name for name in names if name.lower().endswith(LAUNCH_EXTENSIONS)]
    if not launch:
        return []
    return launch + [name for name in names if name not in launch]


def extract_chd(emurun, chdman_exe, sleep=None, dialog=None, wait=None):
    """Extract MAME chd CD-ROM to CUE/BIN.

    Args:
        emurun: Emulation run state dict containing chds, folder, swl_name, set_name
        chdman_exe: Path to chdman executable
        sleep: Optional legacy sleep callback (milliseconds)
        dialog: Optional dialog for progress updates
        wait: Optional abort-aware ``wait(milliseconds) -> bool``; ``True``
            stops chdman, removes the partial output and raises
            ``ShutdownRequested``

    Returns:
        Empty string on success.

    Raises:
        CHDExtractionCancelled: If user cancels via dialog
        ShutdownRequested: If the host asks to stop during the extraction
        CHDExtractionError: If chdman fails
    """
    wait = resolve_wait(wait, sleep)

    log("UMSA Emu: starting chd extract", level='info')
    folder = emurun['folder']
    chd_name = os.path.basename(emurun['chds'][0])
    # dc needs gdi extension
    if emurun['swl_name'] == 'dc':
        file_ext = '.gdi'
    else:
        file_ext = '.cue'
    launch_file = chd_name + file_ext
    # check if chd is already converted
    if os.path.isdir(folder):
        extracted = _extracted_files(folder, launch_file)
        if extracted:
            emurun['extractcd'] = extracted
            return ""
        # leftover without a launch file: extract again
        log(f"UMSA Emu: removing incomplete chd folder {folder}", level='warning')
        shutil.rmtree(folder)

    proc = None
    try:
        # the folder gets its name only when chdman finished: a cancel, an
        # error or a shutdown removes the staging folder
        with staged_dir(folder) as staging:
            proc = subprocess.Popen(
                [chdman_exe, 'extractcd', '-i', emurun['chds'][0], '-o',
                 os.path.join(staging, launch_file)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            percent = 0
            while proc.poll() is None:
                progress = parse_chdman_progress(
                    proc.stderr.read(34).decode('utf-8', errors='ignore'))
                if progress is not None:
                    percent = progress
                if dialog:
                    dialog.update(percent, f'extracting chd: {percent}')
                if dialog and dialog.iscanceled():
                    _terminate_and_reap_process(proc)
                    raise CHDExtractionCancelled("CHD extraction canceled")
                if wait(250):
                    log("UMSA Emu: shutdown requested, stopping chdman",
                        level='warning')
                    _terminate_and_reap_process(proc)
                    raise ShutdownRequested("shutdown during CHD extraction")
            return_code = proc.wait()
            log(f"UMSA Emu: chd extract: RC = {return_code}", level='debug')
            if return_code != 0:
                raise CHDExtractionError(
                    f"chdman extraction failed with exit code {return_code}")
        emurun['extractcd'] = [launch_file]
        return ""
    except (CHDExtractionCancelled, ShutdownRequested, CHDExtractionError):
        raise
    except Exception:
        if proc is not None:
            _terminate_and_reap_process(proc)
        raise
    finally:
        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()

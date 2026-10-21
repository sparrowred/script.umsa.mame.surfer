"""CHD extraction, cancellation and cleanup."""

import os
import shutil
import subprocess

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


def _remove_partial_chd(folder):
    """Remove the new extraction directory and any partial CHD output files."""
    if os.path.isdir(folder):
        shutil.rmtree(folder)


def extract_chd(emurun, chdman_exe, sleep=None, dialog=None):
    """Extract MAME chd CD-ROM to CUE/BIN.

    Args:
        emurun: Emulation run state dict containing chds, folder, swl_name, set_name
        chdman_exe: Path to chdman executable
        sleep: Optional sleep callback (milliseconds)
        dialog: Optional dialog for progress updates

    Returns:
        Empty string on success.

    Raises:
        CHDExtractionCancelled: If user cancels via dialog
        CHDExtractionError: If chdman fails
    """
    import logging
    log = logging.getLogger(__name__)

    log.info("UMSA Emu: starting chd extract")
    chd_name = os.path.basename(emurun['chds'][0])
    # dc needs gdi extension
    if emurun['swl_name'] == 'dc':
        file_ext = '.gdi'
    else:
        file_ext = '.cue'
    # check if chd is already converted
    if os.path.exists(emurun['folder']):
        emurun['extractcd'] = os.listdir(emurun['folder'])
        return ""
    os.mkdir(emurun['folder'])
    output_file = os.path.join(emurun['folder'], chd_name + file_ext)
    log.debug("UMSA Emu: create process")
    proc = None
    try:
        proc = subprocess.Popen(
            [chdman_exe, 'extractcd', '-i', emurun['chds'][0], '-o',
             output_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        percent = 0
        log.debug("UMSA Emu: checking process")
        while proc.poll() is None:
            chdman_progress = proc.stderr.read(34)
            rpos = str(chdman_progress)[::-1].find('%')
            if rpos > -1:
                pos = len(chdman_progress) - rpos - 1
                try:
                    percent = int(float(chdman_progress[pos-4:pos]))
                except ValueError:
                    pass
            if dialog:
                dialog.update(percent, f'extracting chd: {percent}')
            if dialog and dialog.iscanceled():
                _terminate_and_reap_process(proc)
                _remove_partial_chd(emurun['folder'])
                raise CHDExtractionCancelled("CHD extraction canceled")
            if sleep:
                sleep(250)
            else:
                import time
                time.sleep(0.25)
        return_code = proc.wait()
        log.debug(f"UMSA Emu extract_rom: chd extract: RC = {return_code}")
        if return_code == 0:
            emurun['extractcd'] = [chd_name + file_ext]
            return ""
        _remove_partial_chd(emurun['folder'])
        raise CHDExtractionError(
            f"chdman extraction failed with exit code {return_code}")
    except CHDExtractionCancelled:
        raise
    except Exception:
        if proc is not None:
            _terminate_and_reap_process(proc)
        if os.path.isdir(emurun['folder']):
            _remove_partial_chd(emurun['folder'])
        raise
    finally:
        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
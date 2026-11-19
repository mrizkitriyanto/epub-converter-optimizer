"""Linking the installed models into a data folder of a test's own (agent decision Q-7)."""

import subprocess
import sys
from pathlib import Path


def link_dir(dst: Path, src: Path) -> None:
    """Make `dst` a link to the folder `src`. Windows gets a junction, which needs no admin rights
    (a symlink needs Developer Mode). Python 3.12 removes a junction without following it, so
    clearing a folder that holds one, as pytest does with its temp folders, leaves `src` alone."""
    if sys.platform == "win32":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(dst), str(src)], check=True, capture_output=True
        )
    else:
        dst.symlink_to(src, target_is_directory=True)

# ./xtrshow/__init__.py
# License: Apache-2.0 (disclaimer at bottom of file)
"""xtrshow - Interactive file tree selector for LLM workflows"""

import shutil
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from pathlib import Path

__version__ = "1.3.0"

# Every artifact either tool writes lives under one project-local directory.
# Before 1.3 these were three separate entries in the project root.
XTR_DIRNAME = ".xtr"

_LEGACY_LAYOUT = (
    (".xtrpatch", "backup"),
    (".xtrshow_manifest", "manifest"),
    (".xtrshow", "multi"),
)


def get_version():
    """
    Installed distribution version, or a placeholder when running from a
    source tree that was never pip-installed.

    Lives here rather than in cli.py so that importing the patcher does not
    drag in the TUI -- cli.py imports curses at module scope, which is absent
    on any curses-less interpreter (Pyodide/WASM, minimal containers), and
    repatch.py itself needs nothing beyond the standard library.
    """
    try:
        return _pkg_version("xtrshow")
    except PackageNotFoundError:
        return "unknown (not installed)"


def xtr_root(base=None):
    """Root of the project-local state directory.

    Resolved at call time rather than import time: both CLIs are invoked from
    whatever directory the user is in, and the test suite chdirs between cases.
    """
    return (Path.cwd() if base is None else Path(base)) / XTR_DIRNAME


def backup_root(base=None):
    """Where xtrpatch keeps backups, patch archives, logs and checksums."""
    return xtr_root(base) / "backup"


def manifest_path(base=None):
    """Where xtrshow records the last selection for --update."""
    return xtr_root(base) / "manifest"


def multi_dir(base=None):
    """Default destination for `xtrshow --multi`."""
    return xtr_root(base) / "multi"


def migrate_legacy_state(base=None):
    """Fold pre-1.3 state into .xtr/, returning the (src, dest) pairs moved.

    Each entry moves only when the legacy path exists and its .xtr/
    counterpart does not, so an existing .xtr/ is never clobbered and an
    interrupted run resumes where it left off. Backups are a safety net --
    leaving them stranded under .xtrpatch/ would quietly break --revert, so
    this runs automatically rather than waiting to be asked.
    """
    root = Path.cwd() if base is None else Path(base)
    moved = []
    for legacy_name, new_name in _LEGACY_LAYOUT:
        src = root / legacy_name
        dest = xtr_root(root) / new_name
        if not src.exists() or dest.exists():
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        except OSError:
            continue
        moved.append((src, dest))
    return moved
# Copyright Michael Godfrey 2026 | aloecraft.org <michael@aloecraft.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

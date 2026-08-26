# ./xtrshow/__init__.py
# License: Apache-2.0 (disclaimer at bottom of file)
"""xtrshow - Interactive file tree selector for LLM workflows"""

from importlib.metadata import version as _pkg_version, PackageNotFoundError

__version__ = "1.1.0"


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

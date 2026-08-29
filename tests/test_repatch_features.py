# ./tests/test_repatch_features.py
# License: Apache-2.0 (disclaimer at bottom of file)
import os
import pytest
from pathlib import Path
from xtrshow.repatch import apply_changes, parse_multi_file_patch


def test_header_formats(tmp_path):
    """
    Verify that all header formats are parsed correctly:
    <<<<
    <<<< 10
    <<<< 10:20
    """

    # Setup
    target_file = tmp_path / "test.py"
    target_file.write_text("line1\nline2\nline3\nline4\nline5\n")

    # 1. Test Range Format (10:20)
    # We use a hint of '3' to target 'line3' (1-based index)
    patch_content = f"""
--- a/{target_file}
<<<< 3:5
line3
====
UPDATED_3
>>>>
"""
    changes = parse_multi_file_patch(patch_content)
    # Verify parsing extracted the start hint '3' ignoring the ':5'
    assert changes[str(target_file)][0]["hint"] == 3

    apply_changes(changes)
    assert "UPDATED_3" in target_file.read_text()

    # 2. Test Single Number Format (10)
    patch_content_2 = f"""
--- a/{target_file}
<<<< 4
line4
====
UPDATED_4
>>>>
"""
    changes_2 = parse_multi_file_patch(patch_content_2)
    assert changes_2[str(target_file)][0]["hint"] == 4

    apply_changes(changes_2)
    assert "UPDATED_4" in target_file.read_text()

    # 3. Test No Hint Format (<<<<)
    patch_content_3 = f"""
--- a/{target_file}
<<<<
line5
====
UPDATED_5
>>>>
"""
    changes_3 = parse_multi_file_patch(patch_content_3)
    assert changes_3[str(target_file)][0]["hint"] is None

    apply_changes(changes_3)
    assert "UPDATED_5" in target_file.read_text()


def test_atomic_versioning_and_archiving(tmp_path):
    """
    Verify that backups and patch archives increment in lock-step and use target filename.
    Step 1: app.py.orig + app.py.patch
    Step 2: app.py.1.orig + app.py.1.patch
    """

    # Setup Project
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    # Create Target
    target_file = project_dir / "app.py"
    target_file.write_text("v0\n")

    # --- Round 1 (v0 -> v1) ---
    patch_1 = project_dir / "change_a.patch"
    patch_1.write_text(f"--- a/app.py\n<<<< 1\nv0\n====\nv1\n>>>>")

    # Run
    with open(patch_1, "r") as f:
        content = f.read()
    changes = parse_multi_file_patch(content)
    apply_changes(changes, patch_source_path=str(patch_1))

    # Assertions Round 1
    assert target_file.read_text() == "v1\n"

    # Check Backup v0
    backup_v0 = project_dir / ".xtr" / "backup" / "app.py.orig"
    assert backup_v0.exists()
    assert backup_v0.read_text() == "v0\n"

    # Check Patch Archive v0
    # NEW: Stored as app.py.patch (next to app.py.orig), NOT change_a.patch
    archive_v0 = project_dir / ".xtr" / "backup" / "app.py.patch"
    assert archive_v0.exists()
    assert archive_v0.read_text() == patch_1.read_text()

    # --- Round 2 (v1 -> v2) ---
    patch_2 = project_dir / "change_b.patch"
    patch_2.write_text(f"--- a/app.py\n<<<< 1\nv1\n====\nv2\n>>>>")

    with open(patch_2, "r") as f:
        content = f.read()
    changes = parse_multi_file_patch(content)
    apply_changes(changes, patch_source_path=str(patch_2))

    # Assertions Round 2
    assert target_file.read_text() == "v2\n"

    # Check Backup v1
    backup_v1 = project_dir / ".xtr" / "backup" / "app.py.1.orig"
    assert backup_v1.exists()
    assert backup_v1.read_text() == "v1\n"

    # Check Patch Archive v1
    # NEW: Stored as app.py.1.patch
    archive_v1 = project_dir / ".xtr" / "backup" / "app.py.1.patch"
    assert archive_v1.exists()
    assert archive_v1.read_text() == patch_2.read_text()


def test_multi_file_patching(tmp_path):
    """Test applying changes to two files in one pass."""

    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"

    file_a.write_text("content_a\n")
    file_b.write_text("content_b\n")

    patch_content = f"""
--- a/{file_a}
<<<<
content_a
====
new_a
>>>>

--- a/{file_b}
<<<<
content_b
====
new_b
>>>>
"""
    changes = parse_multi_file_patch(patch_content)

    # We simulate apply_changes loop here slightly to handle paths that might vary in test env
    apply_changes(changes)

    assert file_a.read_text() == "new_a\n"
    assert file_b.read_text() == "new_b\n"


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

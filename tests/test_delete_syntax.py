# ./tests/test_delete_syntax.py
# License: Apache-2.0 (disclaimer at bottom of file)
import os
import pytest
from xtrshow.repatch import apply_changes, parse_multi_file_patch


def test_delete_file_shorthand(tmp_path):
    """! DELETE FILE removes the file and creates a backup."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "old.py"
    target.write_text("def legacy(): pass\n")

    patch_content = """
--- a/old.py
! DELETE FILE
"""
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    assert not target.exists()
    assert (project_dir / ".xtr" / "backup" / "old.py.orig").exists()


def test_delete_file_shorthand_case_variants(tmp_path):
    """! DELETE and !DELETE FILE are both accepted."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    for i, directive in enumerate(["! DELETE", "!DELETE FILE"]):
        name = f"file_{i}.py"
        target = project_dir / name
        target.write_text("content\n")

        patch_content = f"--- a/{name}\n{directive}\n"
        changes = parse_multi_file_patch(patch_content)
        apply_changes(changes)

        assert not target.exists(), f"{directive!r} should have deleted {name}"


def test_delete_file_shorthand_mixed_with_modify(tmp_path):
    """A patch that modifies one file and shorthand-deletes another."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    keep = project_dir / "keep.py"
    kill = project_dir / "kill.py"
    keep.write_text("v1\n")
    kill.write_text("dead code\n")

    START, MID, END = "<" * 4, "=" * 4, ">" * 4
    patch_content = f"""
--- a/keep.py
{START}
v1
{MID}
v2
{END}

--- a/kill.py
! DELETE FILE
"""
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    assert keep.read_text() == "v2\n"
    assert not kill.exists()


def test_delete_file_shorthand_with_annotation(tmp_path):
    """Annotation before ! DELETE FILE is preserved."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "annotated.py"
    target.write_text("old\n")

    patch_content = """
--- a/annotated.py
@ Removing deprecated module
! DELETE FILE
"""
    changes = parse_multi_file_patch(patch_content)
    assert changes["annotated.py"][0]["annotation"] == "Removing deprecated module"

    apply_changes(changes)
    assert not target.exists()


def test_delete_file_shorthand_produces_backup(tmp_path):
    """! DELETE FILE backup is revert-able."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "revertme.py"
    original = "important stuff\n"
    target.write_text(original)

    patch_content = "--- a/revertme.py\n! DELETE FILE\n"
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    assert not target.exists()
    backup = project_dir / ".xtr" / "backup" / "revertme.py.orig"
    assert backup.exists()
    assert backup.read_text() == original


def test_old_empty_block_delete_still_works(tmp_path):
    """The original empty-search/empty-replace syntax remains functional."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "legacy.py"
    target.write_text("old\n")

    patch_content = "--- a/legacy.py\n<<<<\n====\n>>>>\n"
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    assert not target.exists()


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

# ./tests/test_repatch_backup.py
# License: Apache-2.0 (disclaimer at bottom of file)
import os
import shutil
from pathlib import Path
from xtrshow.repatch import apply_changes, create_backup


def test_backup_creation(tmp_path):
    """Test that applying changes creates a valid backup file in .xtr/backup/"""

    # Setup: Create a fake project structure
    # /tmp/proj/src/main.py
    project_dir = tmp_path / "proj"
    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True)

    target_file = src_dir / "main.py"
    original_content = "def hello():\n    print('world')\n"
    target_file.write_text(original_content)

    # Change CWD to project_dir so relative paths work as expected
    os.chdir(project_dir)

    # Define a patch
    changes = {
        "src/main.py": [
            {
                "hint": None,
                "search": ["def hello():", "    print('world')"],
                "replace": ["def hello():", "    print('patched')"],
            }
        ]
    }

    # Run the patcher
    apply_changes(changes)

    # Assertions

    # 1. Verify the file was actually patched
    assert "print('patched')" in target_file.read_text()

    # 2. Verify backup directory exists
    backup_dir = project_dir / ".xtr" / "backup"
    assert backup_dir.exists()
    assert backup_dir.is_dir()

    # 3. Verify backup file exists at correct subpath
    # .xtr/backup/src/main.py.orig
    backup_file = backup_dir / "src" / "main.py.orig"
    assert backup_file.exists()

    # 4. Verify backup content matches ORIGINAL content
    assert backup_file.read_text() == original_content
    assert "print('patched')" not in backup_file.read_text()


def test_backup_nested_structure(tmp_path):
    """Test deep nesting logic for backups"""
    project_dir = tmp_path / "deep_proj"
    target_file = project_dir / "a" / "b" / "c" / "script.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("old_content")

    os.chdir(project_dir)

    changes = {
        str(Path("a/b/c/script.py")): [
            {"hint": None, "search": ["old_content"], "replace": ["new_content"]}
        ]
    }

    apply_changes(changes)

    backup_file = project_dir / ".xtr" / "backup" / "a" / "b" / "c" / "script.py.orig"
    assert backup_file.exists()
    assert backup_file.read_text() == "old_content"


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

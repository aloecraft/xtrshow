# ./tests/test_versioning.py
# License: Apache-2.0 (disclaimer at bottom of file)
import os
from pathlib import Path
from xtrshow.repatch import apply_changes


def test_versioned_backups_and_archives(tmp_path):
    """Test that backups and patch archives increment correctly."""

    # Setup Project
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    # 1. Create Source File
    target_file = project_dir / "script.py"
    target_file.write_text("v0 content\n")

    # 2. Create Patch File 1 (Mod v0 -> v1)
    # Note: Filename is update_1.patch, but archive should be script.py.patch
    patch_1 = project_dir / "update_1.patch"
    patch_1.write_text("<<<<\nv0 content\n====\nv1 content\n>>>>")

    # 3. Apply Patch 1
    changes_1 = {
        str(target_file): [
            {"hint": None, "search": ["v0 content"], "replace": ["v1 content"]}
        ]
    }
    apply_changes(changes_1, patch_source_path=str(patch_1))

    # ASSERTIONS ROUND 1
    assert target_file.read_text() == "v1 content\n"

    # Check Backup v0
    backup_v0 = project_dir / ".xtr" / "backup" / "script.py.orig"
    assert backup_v0.exists()
    assert backup_v0.read_text() == "v0 content\n"

    # Check Patch Archive v0
    # NEW BEHAVIOR: Named after TARGET file (script.py.patch), not source patch file
    archive_v0 = project_dir / ".xtr" / "backup" / "script.py.patch"
    assert archive_v0.exists()
    assert archive_v0.read_text() == patch_1.read_text()

    # ---------------------------------------------------------

    # 4. Create Patch File 2 (Mod v1 -> v2)
    patch_2 = project_dir / "update_2.patch"
    patch_2.write_text("<<<<\nv1 content\n====\nv2 content\n>>>>")

    # 5. Apply Patch 2
    changes_2 = {
        str(target_file): [
            {"hint": None, "search": ["v1 content"], "replace": ["v2 content"]}
        ]
    }
    apply_changes(changes_2, patch_source_path=str(patch_2))

    # ASSERTIONS ROUND 2
    assert target_file.read_text() == "v2 content\n"

    # Check Backup v1
    backup_v1 = project_dir / ".xtr" / "backup" / "script.py.1.orig"
    assert backup_v1.exists()
    assert backup_v1.read_text() == "v1 content\n"

    # Check Patch Archive v1
    # NEW BEHAVIOR: Named script.py.1.patch
    archive_v1 = project_dir / ".xtr" / "backup" / "script.py.1.patch"
    assert archive_v1.exists()
    assert archive_v1.read_text() == patch_2.read_text()


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

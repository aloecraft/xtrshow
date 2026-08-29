# ./tests/test_absolute_paths.py
# License: Apache-2.0 (disclaimer at bottom of file)
import os
from pathlib import Path

from xtrshow.repatch import (
    ABS_BACKUP_PREFIX,
    apply_changes,
    parse_multi_file_patch,
    revert_file,
)


def _hunk(search, replace):
    return f"<<\n{search}\n====\n{replace}\n>>>>\n"


# --- Header path parsing -------------------------------------------------


def test_diff_prefix_keeps_absolute_path(tmp_path):
    """'--- a/usr/local/x.py' must not silently become relative 'usr/local/x.py'."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()

    target = ext_dir / "operations.py"
    target.write_text("def sup():\n    return 1\n")

    os.chdir(project_dir)

    content = f"--- a{target}\n" + _hunk("def sup():\n    return 1", "def sup():\n    return 2")
    changes = parse_multi_file_patch(content)

    assert list(changes.keys()) == [str(target)]

    apply_changes(changes)
    assert target.read_text() == "def sup():\n    return 2\n"


def test_b_prefix_keeps_absolute_path(tmp_path):
    """The '+++ b/' form loses its leading slash the same way '--- a/' does."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()

    target = ext_dir / "operations.py"
    target.write_text("old\n")

    os.chdir(project_dir)

    changes = parse_multi_file_patch(f"+++ b{target}\n" + _hunk("old", "new"))
    assert list(changes.keys()) == [str(target)]

    apply_changes(changes)
    assert target.read_text() == "new\n"


def test_diff_prefix_still_prefers_relative_reading(tmp_path):
    """Git's own meaning wins: 'a/usr/x.py' is repo-relative when that file exists."""
    project_dir = tmp_path / "proj"
    (project_dir / "usr").mkdir(parents=True)
    target = project_dir / "usr" / "x.py"
    target.write_text("old\n")

    os.chdir(project_dir)

    changes = parse_multi_file_patch("--- a/usr/x.py\n" + _hunk("old", "new"))
    assert list(changes.keys()) == ["usr/x.py"]

    apply_changes(changes)
    assert target.read_text() == "new\n"


def test_diff_prefix_unresolvable_path_stays_relative(tmp_path):
    """With nothing on disk to disambiguate, fall back to git's reading."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    changes = parse_multi_file_patch("--- a/nowhere/new.py\n" + _hunk("", "created"))
    assert list(changes.keys()) == ["nowhere/new.py"]


# --- Backup namespacing for out-of-tree targets --------------------------


def test_out_of_tree_backup_mirrors_absolute_path(tmp_path):
    """Targets outside the cwd land under _abs/, not flattened to a basename."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()

    target = ext_dir / "mod.py"
    target.write_text("old\n")

    os.chdir(project_dir)
    apply_changes({str(target): [{"hint": None, "search": ["old"], "replace": ["new"]}]})

    resolved = target.resolve()
    mirrored = Path(ABS_BACKUP_PREFIX).joinpath(
        *[p for p in resolved.parts if p.strip("/\\")]
    )
    backup = project_dir / ".xtr" / "backup" / (str(mirrored) + ".orig")

    assert backup.exists()
    assert backup.read_text() == "old\n"
    assert not (project_dir / ".xtr" / "backup" / "mod.py.orig").exists()


def test_revert_does_not_cross_same_basename_targets(tmp_path):
    """Two out-of-tree 'mod.py' must not share backups — revert used to swap them."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    beta = tmp_path / "beta"
    beta.mkdir()

    (alpha / "mod.py").write_text("ALPHA-OLD\n")
    (beta / "mod.py").write_text("BETA-OLD\n")

    os.chdir(project_dir)
    apply_changes(
        {
            str(alpha / "mod.py"): [
                {"hint": None, "search": ["ALPHA-OLD"], "replace": ["ALPHA-NEW"]}
            ],
            str(beta / "mod.py"): [
                {"hint": None, "search": ["BETA-OLD"], "replace": ["BETA-NEW"]}
            ],
        }
    )

    assert (alpha / "mod.py").read_text() == "ALPHA-NEW\n"
    assert (beta / "mod.py").read_text() == "BETA-NEW\n"

    revert_file(str(alpha / "mod.py"))
    revert_file(str(beta / "mod.py"))

    assert (alpha / "mod.py").read_text() == "ALPHA-OLD\n"
    assert (beta / "mod.py").read_text() == "BETA-OLD\n"


def test_revert_in_tree_ignores_out_of_tree_namesake(tmp_path):
    """An external namesake used to claim v1 and get restored over the in-tree file."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()

    in_tree = project_dir / "mod.py"
    in_tree.write_text("IN-TREE-OLD\n")
    external = ext_dir / "mod.py"
    external.write_text("EXTERNAL-OLD\n")

    os.chdir(project_dir)
    apply_changes(
        {
            "mod.py": [
                {"hint": None, "search": ["IN-TREE-OLD"], "replace": ["IN-TREE-NEW"]}
            ],
            str(external): [
                {"hint": None, "search": ["EXTERNAL-OLD"], "replace": ["EXTERNAL-NEW"]}
            ],
        }
    )

    revert_file("mod.py")
    assert in_tree.read_text() == "IN-TREE-OLD\n"
    assert external.read_text() == "EXTERNAL-NEW\n"


def test_no_false_external_modification_warning(tmp_path, capsys):
    """Colliding .last.sha256 files made the second same-basename target look edited."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    beta = tmp_path / "beta"
    beta.mkdir()

    (alpha / "mod.py").write_text("ALPHA-OLD\n")
    (beta / "mod.py").write_text("BETA-OLD\n")

    os.chdir(project_dir)
    apply_changes(
        {str(alpha / "mod.py"): [{"hint": None, "search": ["ALPHA-OLD"], "replace": ["A"]}]}
    )
    capsys.readouterr()
    apply_changes(
        {str(beta / "mod.py"): [{"hint": None, "search": ["BETA-OLD"], "replace": ["B"]}]}
    )

    assert "modified externally" not in capsys.readouterr().out


# --- Creation bookkeeping ------------------------------------------------


def test_created_file_backup_sits_with_its_metadata(tmp_path):
    """Creation passed an unresolved path, so a relative subdir split its bookkeeping."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    apply_changes({"sub/dir/new.py": [{"hint": None, "search": [], "replace": ["print(1)"]}]})

    backup_dir = project_dir / ".xtr" / "backup" / "sub" / "dir"
    assert (backup_dir / "new.py.orig").exists()
    assert (backup_dir / "new.py.last.sha256").exists()
    assert not (project_dir / ".xtr" / "backup" / "new.py.orig").exists()


def test_out_of_tree_creation_is_namespaced(tmp_path):
    """A created file outside the cwd gets the same _abs/ treatment."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()

    os.chdir(project_dir)
    target = ext_dir / "created.py"
    apply_changes({str(target): [{"hint": None, "search": [], "replace": ["print(1)"]}]})

    assert target.read_text() == "print(1)\n"
    assert not (project_dir / ".xtr" / "backup" / "created.py.orig").exists()
    assert list((project_dir / ".xtr" / "backup" / ABS_BACKUP_PREFIX).rglob("created.py.orig"))


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

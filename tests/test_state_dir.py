# ./tests/test_state_dir.py
# License: Apache-2.0 (disclaimer at bottom of file)
"""Everything either tool writes lives under one .xtr/ directory."""

import os
from unittest.mock import patch

import pytest

from xtrshow import (
    backup_root,
    manifest_path,
    migrate_legacy_state,
    multi_dir,
    xtr_root,
)
from xtrshow.cli import main
from xtrshow.repatch import apply_changes, revert_file


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run_export(target_file, extra_argv=None):
    argv = ["xtrshow", "."] + (extra_argv or [])
    with patch("xtrshow.cli.curses.wrapper", return_value=[str(target_file)]), patch(
        "sys.argv", argv
    ):
        main()


def test_paths_are_all_under_one_root(project):
    assert xtr_root() == project / ".xtr"
    for path in (backup_root(), manifest_path(), multi_dir()):
        assert path.parent == project / ".xtr"


def test_paths_follow_the_cwd(tmp_path, monkeypatch):
    """Resolved per call, not frozen at import: both CLIs run from anywhere."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.chdir(a)
    assert backup_root() == a / ".xtr" / "backup"
    monkeypatch.chdir(b)
    assert backup_root() == b / ".xtr" / "backup"


def test_export_writes_manifest_into_xtr(project, capsys):
    f1 = project / "app.py"
    f1.write_text("x = 1\n")

    run_export(f1)
    capsys.readouterr()

    assert manifest_path().read_text().strip() == str(f1)
    assert not (project / ".xtrshow_manifest").exists()


def test_patch_writes_backups_into_xtr(project, capsys):
    target = project / "app.py"
    target.write_text("v0\n")

    apply_changes({str(target): [{"hint": None, "search": ["v0"], "replace": ["v1"]}]})
    capsys.readouterr()

    assert (backup_root() / "app.py.orig").read_text() == "v0\n"
    assert not (project / ".xtrpatch").exists()


def test_multi_export_defaults_into_xtr(project, capsys):
    f1 = project / "app.py"
    f1.write_text("x = 1\n")

    run_export(f1, ["--multi"])
    capsys.readouterr()

    assert len(list(multi_dir().iterdir())) == 1
    assert not (project / ".xtrshow").exists()


def test_migration_moves_all_three_legacy_entries(project):
    (project / ".xtrpatch").mkdir()
    (project / ".xtrpatch" / "app.py.orig").write_text("original\n")
    (project / ".xtrshow_manifest").write_text("app.py\n")
    (project / ".xtrshow").mkdir()
    (project / ".xtrshow" / "app.py.xtr.md").write_text("block\n")

    moved = migrate_legacy_state()

    assert len(moved) == 3
    assert (backup_root() / "app.py.orig").read_text() == "original\n"
    assert manifest_path().read_text() == "app.py\n"
    assert (multi_dir() / "app.py.xtr.md").read_text() == "block\n"
    assert not (project / ".xtrpatch").exists()
    assert not (project / ".xtrshow_manifest").exists()
    assert not (project / ".xtrshow").exists()


def test_migration_preserves_revert_history(project, capsys):
    """A pre-1.3 backup must still be reachable by --revert after moving."""
    target = project / "app.py"
    target.write_text("edited\n")
    legacy = project / ".xtrpatch"
    legacy.mkdir()
    (legacy / "app.py.orig").write_text("pristine\n")

    migrate_legacy_state()
    revert_file(str(target))
    capsys.readouterr()

    assert target.read_text() == "pristine\n"


def test_migration_never_clobbers_existing_state(project):
    (project / ".xtrpatch").mkdir()
    (project / ".xtrpatch" / "app.py.orig").write_text("legacy\n")
    backup_root().mkdir(parents=True)
    (backup_root() / "app.py.orig").write_text("current\n")

    moved = migrate_legacy_state()

    assert moved == []
    assert (backup_root() / "app.py.orig").read_text() == "current\n"
    assert (project / ".xtrpatch" / "app.py.orig").read_text() == "legacy\n"


def test_migration_is_idempotent(project):
    (project / ".xtrshow_manifest").write_text("app.py\n")

    first = migrate_legacy_state()
    second = migrate_legacy_state()

    assert len(first) == 1
    assert second == []
    assert manifest_path().read_text() == "app.py\n"


def test_migration_resumes_after_partial_run(project):
    """One entry already migrated, one still legacy: only the latter moves."""
    manifest_path().parent.mkdir(parents=True)
    manifest_path().write_text("app.py\n")
    (project / ".xtrpatch").mkdir()
    (project / ".xtrpatch" / "app.py.orig").write_text("original\n")

    moved = migrate_legacy_state()

    assert [dest.name for _, dest in moved] == ["backup"]
    assert (backup_root() / "app.py.orig").read_text() == "original\n"


def test_migration_noop_on_clean_project(project):
    assert migrate_legacy_state() == []
    assert not xtr_root().exists()


def test_update_reads_migrated_manifest(project, capsys):
    """--update off a pre-1.3 manifest works without re-running the TUI."""
    f1 = project / "app.py"
    f1.write_text("x = 1\n")
    (project / ".xtrshow_manifest").write_text("app.py\n")

    with patch("sys.argv", ["xtrshow", ".", "--update"]):
        main()

    out = capsys.readouterr().out
    assert "--- a/app.py" in out
    assert manifest_path().exists()
    assert not (project / ".xtrshow_manifest").exists()


def test_migration_survives_absolute_path_backups(project):
    """The _abs/ mirror for out-of-tree targets moves with everything else."""
    legacy = project / ".xtrpatch" / "_abs" / "elsewhere"
    legacy.mkdir(parents=True)
    (legacy / "far.py.orig").write_text("far\n")

    migrate_legacy_state()

    assert (backup_root() / "_abs" / "elsewhere" / "far.py.orig").read_text() == "far\n"


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

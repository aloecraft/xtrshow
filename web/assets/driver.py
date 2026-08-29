"""
Browser driver for the xtrshow live demo.

Thin adapter only: every patching decision is made by the real, unmodified
``xtrshow.repatch`` module vendored under /vendor. This file just prepares a
working directory in Pyodide's in-memory filesystem, captures stdout, and hands
results back to JavaScript as JSON.
"""

import contextlib
import io
import json
import os
import shutil
from pathlib import Path

import xtrshow.repatch as rp
from xtrshow import get_version

ROOT = Path("/demo")
PATCH_NAME = "xpatch.txt"


def _workdir(scenario):
    return ROOT / scenario


def reset(scenario, files_json):
    """Wipe and rebuild a scenario's working directory from its seed files."""
    files = json.loads(files_json)
    wd = _workdir(scenario)
    if wd.exists():
        shutil.rmtree(wd)
    wd.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = wd / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return json.dumps({"ok": True})


def _tree(wd):
    """Render the .xtr/backup tree, so the safety net is visible."""
    xp = wd / ".xtr" / "backup"
    if not xp.exists():
        return "(no backups yet — .xtr/backup/ is created on first apply)"
    rows = []
    for p in sorted(xp.rglob("*")):
        if p.is_file():
            rel = p.relative_to(wd)
            size = p.stat().st_size
            rows.append(f"{str(rel):<46} {size:>7} B")
    return "\n".join(rows) if rows else "(empty)"


def _snapshot(wd):
    """Current on-disk state of every non-backup file in the workdir."""
    out = {}
    for p in sorted(wd.rglob("*")):
        if p.is_file() and ".xtr" not in p.parts:
            try:
                out[str(p.relative_to(wd))] = p.read_text()
            except UnicodeDecodeError:
                pass
    return out


def apply_patch(scenario, src_name, src_text, patch_text):
    """
    Write the editor's current buffer to disk, then run the real apply_changes.

    The patch is written to disk too, so xtrpatch archives it next to the
    backup exactly as the CLI does.
    """
    wd = _workdir(scenario)
    wd.mkdir(parents=True, exist_ok=True)

    target = wd / src_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(src_text)

    patch_path = wd / PATCH_NAME
    patch_path.write_text(patch_text)

    cwd = os.getcwd()
    buf = io.StringIO()
    error = None
    try:
        os.chdir(wd)
        changes = rp.parse_multi_file_patch(patch_text)
        if not changes:
            return json.dumps(
                {
                    "report": "No valid blocks found in patch file.",
                    "files": _snapshot(wd),
                    "tree": _tree(wd),
                }
            )
        with contextlib.redirect_stdout(buf):
            rp.apply_changes(changes, patch_source_path=PATCH_NAME)
    except Exception as exc:  # surfaced in the terminal pane, never swallowed
        error = f"{type(exc).__name__}: {exc}"
    finally:
        os.chdir(cwd)

    report = buf.getvalue().rstrip()
    if error:
        report = (report + "\n" if report else "") + f"! Demo driver error: {error}"

    return json.dumps(
        {
            "report": report or "(no output)",
            "files": _snapshot(wd),
            "tree": _tree(wd),
        }
    )


def revert(scenario, patch_text):
    """
    Mirror `xtrpatch --revert <patchfile>`.

    The CLI parses the patch, then reverts every file it names. Reproduced here
    by calling the same two functions in the same order, so the terminal output
    matches what the command prints on a real machine.
    """
    wd = _workdir(scenario)
    cwd = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(wd)
        with contextlib.redirect_stdout(buf):
            changes = rp.parse_multi_file_patch(patch_text)
            if changes:
                print(f"Found {len(changes)} target(s) in patch file to revert.")
                for filepath in changes.keys():
                    rp.revert_file(filepath)
            else:
                print("No valid blocks found in patch file.")
    finally:
        os.chdir(cwd)

    return json.dumps(
        {
            "report": buf.getvalue().rstrip() or "(no output)",
            "files": _snapshot(wd),
            "tree": _tree(wd),
        }
    )


def tree(scenario):
    """Approximate `tree .` over the working directory, minus .xtr/."""
    wd = _workdir(scenario)
    if not wd.exists():
        return json.dumps({"report": "(nothing here yet)"})

    entries = sorted(
        p for p in wd.iterdir() if p.name != ".xtr"
    )
    lines = ["."]
    for i, p in enumerate(entries):
        lines.append(f"{'└── ' if i == len(entries) - 1 else '├── '}{p.name}")
    # tree(1) counts the root it was pointed at, hence the +1.
    n_dirs = sum(1 for p in entries if p.is_dir()) + 1
    n_files = sum(1 for p in entries if p.is_file())
    lines.append("")
    lines.append(f"{n_dirs} director{'y' if n_dirs == 1 else 'ies'}, {n_files} file{'' if n_files == 1 else 's'}")
    return json.dumps({"report": "\n".join(lines)})


def ls_backups(scenario):
    """`ls .xtr/backup/` — the safety net, made visible."""
    wd = _workdir(scenario)
    xp = wd / ".xtr" / "backup"
    if not xp.exists():
        return json.dumps(
            {"report": "ls: cannot access '.xtr/backup/': No such file or directory"}
        )
    names = sorted(p.name for p in xp.iterdir())
    return json.dumps({"report": "  ".join(names) if names else ""})


def extract(src_name, src_text):
    """
    Reproduce what `xtrshow` writes for a single selected file.

    Mirrors the block construction in xtrshow/cli.py: a --- a/ +++ b/ header
    pair, then the file fenced and prefixed with right-aligned line numbers.
    """
    content = src_text.replace("\r\n", "\n")
    lines = content.splitlines()
    width = len(str(len(lines))) if lines else 1
    body = "\n".join(f"{i + 1:>{width}}:{line}" for i, line in enumerate(lines))
    ext = os.path.splitext(src_name)[1]
    lang = ext[1:] if ext.startswith(".") else ext
    fence = "```"
    return f"--- a/{src_name}\n+++ b/{src_name}\n{fence} {lang}\n{body}\n{fence}\n"


def version():
    return get_version()

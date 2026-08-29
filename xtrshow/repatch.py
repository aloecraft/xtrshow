#!/usr/bin/env python3

# ./xtrshow/repatch.py
# License: Apache-2.0 (disclaimer at bottom of file)
import sys
import re
import argparse
import difflib
import os
import shutil
from pathlib import Path

from xtrshow import (
    XTR_DIRNAME,
    backup_root as default_backup_root,
    get_version,
    migrate_legacy_state,
)

# Subdirectory of .xtr/backup/ that mirrors targets living outside the cwd.
ABS_BACKUP_PREFIX = "_abs"


# One definition of a hunk opener, shared by the parser and the drift check.
HUNK_OPENER_RE = re.compile(r"^(?:<<<<|<<)\s*(\d+)?(?:[:~](\d+))?\s*$")


def normalize(line):
    """Normalize line for comparison (strip whitespace)."""
    return line.strip()


def _is_file_header(line):
    """True for the '--- a/path' family of section headers."""
    return (
        line.startswith("--- ") or line.startswith("+++ ") or line.startswith("File: ")
    )


def _opens_new_hunk(lines, idx):
    """True if lines[idx] is a file header that structurally begins another hunk.

    Guarded by a lookahead rather than matching any header-shaped line, because
    replacement text legitimately contains them -- xtrshow's own export format
    emits '--- a/path', so patching a file that documents the format would
    otherwise break. Only a header followed (past blanks and annotations) by a
    hunk opener counts as structure.
    """
    if not _is_file_header(lines[idx]):
        return False
    j = idx + 1
    while j < len(lines):
        stripped = lines[j].strip()
        if not stripped or stripped.startswith("@") or _is_file_header(lines[j]):
            j += 1
            continue
        return HUNK_OPENER_RE.match(stripped) is not None
    return False


def count_hunk_openers(content):
    """How many hunks the patch text *claims*, counted independently of parsing.

    The backstop for the drift check: if the parser produces fewer hunks than
    there are openers, something was swallowed and the caller can say so
    instead of leaving the difference invisible.
    """
    return sum(1 for line in content.splitlines() if HUNK_OPENER_RE.match(line.strip()))


def _parse_wildcard(line):
    """
    Parse a ~~~~ wildcard line. Returns (is_wildcard, max_lines, exact) or (False, None, None).
      ~~~~    -> (True, None,  False)  unbounded
      ~~~~4   -> (True, 4,     False)  up to 4 lines
      ~~~~=4  -> (True, 4,     True)   exactly 4 lines
    """
    stripped = line.strip()
    if not stripped.startswith("~~~~"):
        return False, None, None
    rest = stripped[4:]
    if not rest:
        return True, None, False
    if rest.startswith("="):
        try:
            return True, int(rest[1:]), True
        except ValueError:
            return False, None, None
    try:
        return True, int(rest), False
    except ValueError:
        return False, None, None


def _split_on_wildcards(lines):
    """
    Split a list of search/tail lines into segments separated by wildcard markers.
    Returns a list of (segment_lines, max_skip, exact) tuples, where max_skip/exact
    describe the wildcard that follows this segment (None if it's the last segment).
    """
    segments = []
    current = []
    for line in lines:
        is_wc, max_lines, exact = _parse_wildcard(line)
        if is_wc:
            segments.append((current, max_lines, exact))
            current = []
        else:
            current.append(line)
    segments.append((current, None, None))  # final segment, no trailing wildcard
    return segments


def _match_segment(file_lines, file_idx, seg_lines):
    """
    Match a list of non-wildcard lines against file_lines starting at file_idx,
    skipping blank lines in the file (existing fuzzy behaviour).
    Returns the file index after the last matched line, or None on failure.
    """
    norm_seg = [normalize(l) for l in seg_lines if normalize(l)]
    seg_idx = 0
    while seg_idx < len(norm_seg):
        if file_idx >= len(file_lines):
            return None
        norm_file = normalize(file_lines[file_idx])
        if not norm_file:
            file_idx += 1
            continue
        if norm_file != norm_seg[seg_idx]:
            return None
        file_idx += 1
        seg_idx += 1
    return file_idx


def _match_wildcard(file_lines, file_idx, next_seg_lines, max_skip, exact):
    """
    After a wildcard marker, advance file_idx until the first line of next_seg_lines
    matches, respecting max_skip and exact constraints.

    ~~~~     (max_skip=None, exact=False): scan to EOF
    ~~~~4    (max_skip=4,    exact=False): next anchor within 4 lines (positions +1..+4+1)
    ~~~~=4   (max_skip=4,    exact=True):  next anchor at exactly position +4+1

    Returns the file index AT the start of the next segment, or None on failure.
    """
    norm_next = [normalize(l) for l in next_seg_lines if normalize(l)]
    # An empty final segment after a wildcard is always fine — wildcard consumed to EOF
    if not norm_next:
        return file_idx

    first_anchor = norm_next[0]

    if exact:
        # Must match at exactly file_idx + max_skip + 1 (skip exactly max_skip lines)
        target = file_idx + max_skip
        # Advance past blank lines to land on a content line at or after target
        pos = file_idx
        content_seen = 0
        while pos < len(file_lines):
            if normalize(file_lines[pos]):
                if content_seen == max_skip:
                    if normalize(file_lines[pos]) == first_anchor:
                        return pos
                    return None
                content_seen += 1
            pos += 1
        return None

    # Bounded or unbounded: scan forward up to max_skip content lines
    content_skipped = 0
    pos = file_idx
    while pos < len(file_lines):
        if max_skip is not None and content_skipped > max_skip:
            return None
        norm_line = normalize(file_lines[pos])
        if norm_line:
            if norm_line == first_anchor:
                return pos
            content_skipped += 1
        pos += 1
    return None


def _difference_kind(a, b):
    """Name the way two normalized lines differ, when it is a familiar one."""
    if a.split() == b.split():
        return "interior whitespace differs"
    if a.lower() == b.lower():
        return "capitalization differs"
    if a.replace('"', "'") == b.replace('"', "'"):
        return "quote style differs"
    return None


def _trim(text, width=58):
    text = text.strip()
    return text if len(text) <= width else text[: width - 1] + "…"


def explain_match_failure(file_lines, search_lines):
    """Say why a search block did not match, in terms the writer can act on.

    'Block Not Found' is a dead end: it does not distinguish a line that is
    absent from one that is present but differs by a space. Runs only after a
    match has already failed, so it never costs anything on the success path.
    """
    norm_search = [normalize(l) for l in search_lines if normalize(l)]
    if not norm_search:
        return None

    norm_file = [normalize(l) for l in file_lines]
    anchor = norm_search[0]
    anchor_hits = [n for n, line in enumerate(norm_file, 1) if line == anchor]

    if anchor_hits:
        # The block started matching and then diverged. Naming the line it
        # diverged on is far more useful than naming the block.
        best = None
        for start in anchor_hits:
            file_idx = start - 1
            for depth, want in enumerate(norm_search):
                while file_idx < len(norm_file) and not norm_file[file_idx]:
                    file_idx += 1
                if file_idx >= len(norm_file) or norm_file[file_idx] != want:
                    break
                file_idx += 1
            else:
                continue
            if best is None or depth > best[0]:
                got = norm_file[file_idx] if file_idx < len(norm_file) else ""
                best = (depth, start, file_idx + 1, want, got)

        if best is not None:
            depth, start, file_line, want, got = best
            if not got:
                return (
                    f"matched from line {start} but ran past end of file at "
                    f"search line {depth + 1}"
                )
            kind = _difference_kind(want, got)
            because = f" ({kind})" if kind else ""
            return (
                f"matched from line {start}, diverged at search line "
                f"{depth + 1}: expected '{_trim(want)}', file line {file_line} "
                f"has '{_trim(got)}'{because}"
            )

    # The anchor itself is absent: point at whatever came closest.
    best_ratio, best_n, best_line = 0.0, None, None
    for n, line in enumerate(norm_file, 1):
        if not line:
            continue
        ratio = difflib.SequenceMatcher(None, anchor, line).ratio()
        if ratio > best_ratio:
            best_ratio, best_n, best_line = ratio, n, line

    if best_n is None or best_ratio < 0.6:
        return f"no line resembles '{_trim(anchor)}'"

    kind = _difference_kind(anchor, best_line)
    because = f" ({kind})" if kind else f" ({best_ratio:.0%} similar)"
    return (
        f"no match for '{_trim(anchor)}'; closest is line {best_n} "
        f"'{_trim(best_line)}'{because}"
    )


def find_match(file_lines, search_lines, start_hint=None):
    """Find the best match for search_lines in file_lines, supporting ~~~~ wildcards."""
    segments = _split_on_wildcards(search_lines)

    # Fast path: no wildcards — filter empty segments and use original logic
    has_wildcards = len(segments) > 1 or any(
        _parse_wildcard(l)[0] for l in search_lines
    )

    if not has_wildcards:
        norm_search = [normalize(l) for l in search_lines if normalize(l)]
        if not norm_search:
            return None

        candidates = []
        for i in range(len(file_lines)):
            if normalize(file_lines[i]) != norm_search[0]:
                continue
            file_idx = _match_segment(file_lines, i, search_lines)
            if file_idx is not None:
                candidates.append((i, file_idx))

        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if start_hint is not None:
            return min(candidates, key=lambda x: abs((x[0] + 1) - start_hint))
        print(f"Error: Ambiguous match. Found {len(candidates)} instances of block.")
        return None

    # Wildcard path: find all candidate start positions using the first segment
    first_seg, first_max, first_exact = segments[0]
    norm_first = [normalize(l) for l in first_seg if normalize(l)]

    candidates = []

    # Determine candidate start positions
    if norm_first:
        starts = [
            i
            for i in range(len(file_lines))
            if normalize(file_lines[i]) == norm_first[0]
        ]
    else:
        # Search block starts with a wildcard — every line is a candidate start
        starts = list(range(len(file_lines)))

    for start in starts:
        # Match first segment
        if norm_first:
            file_idx = _match_segment(file_lines, start, first_seg)
            if file_idx is None:
                continue
        else:
            file_idx = start

        # Walk through remaining wildcard + segment pairs
        ok = True
        for seg_idx in range(len(segments) - 1):
            seg_lines, max_skip, exact = segments[seg_idx]
            next_seg_lines = segments[seg_idx + 1][0]

            # Advance past the wildcard to find the next segment
            file_idx = _match_wildcard(
                file_lines, file_idx, next_seg_lines, max_skip, exact
            )
            if file_idx is None:
                ok = False
                break

            # Match the next segment
            file_idx = _match_segment(file_lines, file_idx, next_seg_lines)
            if file_idx is None:
                ok = False
                break

        if ok:
            candidates.append((start, file_idx))

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if start_hint is not None:
        return min(candidates, key=lambda x: abs((x[0] + 1) - start_hint))
    print(f"Error: Ambiguous match. Found {len(candidates)} instances of block.")
    return None


def _strip_diff_prefix(raw_path):
    """
    Strip a git-style 'a/' or 'b/' prefix from a header path.

    An absolute target written as '--- a/usr/local/lib/x.py' loses its leading
    slash to this strip and silently becomes a relative path that resolves
    against the cwd. Git's own reading (repo-relative 'usr/local/lib/x.py')
    wins whenever such a file actually exists; otherwise fall back to reading
    it as the absolute path the leading slash was taken from.
    """
    stripped = raw_path[2:]
    if os.path.exists(stripped):
        return stripped
    if not os.path.isabs(stripped):
        absolute = os.sep + stripped
        if os.path.exists(absolute):
            return absolute
    return stripped


def parse_multi_file_patch(content, default_target=None):
    """Parses a patch file containing multiple file sections."""
    changes = {}
    current_file = default_target
    current_annotation = None
    lines = content.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Capture Annotations
        if stripped.startswith("@"):
            current_annotation = stripped[1:].strip()
            i += 1
            continue

        if (
            line.startswith("--- ")
            or line.startswith("+++ ")
            or line.startswith("File: ")
        ):
            parts = line.split(maxsplit=1)
            if len(parts) > 1:
                raw_path = parts[1].strip()
                if (line.startswith("--- ") and raw_path.startswith("a/")) or (
                    line.startswith("+++ ") and raw_path.startswith("b/")
                ):
                    raw_path = _strip_diff_prefix(raw_path)
                current_file = raw_path
            current_annotation = None  # Reset annotation on file change
            i += 1
            continue

        # ! DELETE FILE — whole-file deletion shorthand
        if stripped.upper() in ("! DELETE FILE", "!DELETE FILE", "! DELETE"):
            if current_file:
                if current_file not in changes:
                    changes[current_file] = []
                changes[current_file].append(
                    {
                        "patch_line": i + 1,
                        "hint": None,
                        "search": [],
                        "replace": [],
                        "tail": [],
                        "annotation": current_annotation or "Delete file",
                    }
                )
                current_annotation = None
            i += 1
            continue

        # Support ':' or '~' for range hints (e.g., 10:15 or 10~15)
        # ALLOW '<<' (2 brackets) as a start marker, but ONLY if the line ends immediately
        # after the hint. This prevents matching C++ streams or bitwise shifts like '<< 5;'.
        block_match = HUNK_OPENER_RE.match(stripped)

        if block_match:
            block_start_line = i + 1

            if not current_file:
                i += 1
                continue

            hint_start = int(block_match.group(1)) if block_match.group(1) else None
            annotation = current_annotation
            current_annotation = None

            def record_malformed(reason):
                """Keep an unclosable hunk as evidence instead of dropping it.

                Silently discarding it is what let one missing '>>>>' swallow
                the hunk after it without a trace.
                """
                changes.setdefault(current_file, []).append(
                    {
                        "patch_line": block_start_line,
                        "hint": None,
                        "search": [],
                        "replace": [],
                        "tail": [],
                        "annotation": annotation,
                        "malformed": reason,
                    }
                )

            i += 1
            search_lines = []
            while (
                i < len(lines)
                and lines[i].strip() != "===="
                and not _opens_new_hunk(lines, i)
            ):
                search_lines.append(lines[i])
                i += 1

            if i >= len(lines) or lines[i].strip() != "====":
                # Deliberately does not advance past the header: the outer loop
                # reparses it, so the hunk that follows survives this one.
                record_malformed("missing ==== separator")
                continue

            i += 1
            replace_lines = []
            tail_lines = []

            # Consume Replace Block (until >>>> OR second ====)
            while i < len(lines):
                s = lines[i].strip()
                if s == ">>>>" or s == "====" or _opens_new_hunk(lines, i):
                    break
                replace_lines.append(lines[i])
                i += 1

            # Check for Tail Context (second ====)
            if i < len(lines) and lines[i].strip() == "====":
                i += 1  # skip second ====
                while (
                    i < len(lines)
                    and lines[i].strip() != ">>>>"
                    and not _opens_new_hunk(lines, i)
                ):
                    tail_lines.append(lines[i])
                    i += 1

            if i >= len(lines) or lines[i].strip() != ">>>>":
                record_malformed("missing >>>> terminator")
                continue

            changes.setdefault(current_file, []).append(
                {
                    "patch_line": block_start_line,
                    "hint": hint_start,
                    "search": search_lines,
                    "replace": replace_lines,
                    "tail": tail_lines,
                    "annotation": annotation,
                }
            )
            i += 1
            continue

        i += 1

    return changes


def _compute_checksum(filepath):
    """Compute SHA256 checksum of a file."""
    import hashlib

    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _save_checksum(backup_path):
    """Write a .sha256 file next to a backup."""
    try:
        checksum = _compute_checksum(backup_path)
        Path(str(backup_path) + ".sha256").write_text(checksum)
    except Exception as e:
        print(f"  ! Warning: Failed to save checksum: {e}")


def _backup_rel_path(filepath):
    """
    Path of a target file *within* the backup tree.

    Files under the cwd mirror their relative path. Files outside it used to
    collapse to their bare basename, so two 'operations.py' from different
    trees shared one set of backups — and --revert could hand back the wrong
    file's contents. Mirror the full absolute path under _abs/ instead so
    distinct targets never share a slot.
    """
    src = Path(filepath).resolve()
    try:
        return src.relative_to(Path.cwd())
    except ValueError:
        pass

    parts = []
    for part in src.parts:
        # Drops the root ('/' -> '') and sanitizes Windows drives ('C:\' -> 'C')
        cleaned = part.strip("/\\").replace(":", "")
        if cleaned:
            parts.append(cleaned)
    return Path(ABS_BACKUP_PREFIX).joinpath(*parts)


def _backup_location(filepath, backup_root=None):
    """Returns (directory inside .xtr/backup, filename) for a target file."""
    rel_path = _backup_rel_path(filepath)
    if backup_root is None:
        backup_root = default_backup_root()
    return backup_root / rel_path.parent, rel_path.name


def _state_checksum_path(filepath):
    """Path of the .last.sha256 file recording the post-patch state."""
    backup_dir, filename = _backup_location(filepath)
    return backup_dir / (filename + ".last.sha256")


def _save_state_checksum(filepath):
    """Record the checksum of the file as it exists NOW (post-patch)."""
    try:
        dest = _state_checksum_path(filepath)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_compute_checksum(filepath))
    except Exception as e:
        print(f"  ! Warning: Failed to save state checksum: {e}")


def _verify_checksum(filepath):
    """
    Check whether filepath still matches the post-patch state checksum
    saved after the last successful patch. Returns True if no state has
    been recorded yet (first patch) or if they match. Returns False and
    prints a warning if the file was edited externally in between.
    """
    try:
        state_path = _state_checksum_path(filepath)
        if not state_path.exists():
            return True  # No prior recorded state, nothing to verify

        expected = state_path.read_text().strip()
        actual = _compute_checksum(filepath)
        if actual != expected:
            print(f"  ⚠️  {filepath} has been modified externally since last patch.")
            print(f"     Saved:   {expected[:12]}...")
            print(f"     Current: {actual[:12]}...")
            print(f"     Backup may not reflect the true original. Continuing anyway.")
            return False
    except Exception as e:
        print(f"  ! Warning: Checksum verification failed: {e}")
    return True


def get_backup_path(src_path, backup_dir_root):
    """Calculates the next available versioned path."""
    base_backup_dir, filename = _backup_location(src_path, backup_dir_root)
    base_backup_dir.mkdir(parents=True, exist_ok=True)

    v0 = base_backup_dir / (filename + ".orig")
    if not v0.exists():
        return v0, 0

    i = 1
    while True:
        next_path = base_backup_dir / (filename + f".{i}.orig")
        if not next_path.exists():
            return next_path, i
        i += 1


def create_backup(filepath):
    """Creates a versioned backup of the file."""
    try:
        src = Path(filepath).resolve()
        dest, version = get_backup_path(src, default_backup_root())
        shutil.copy2(src, dest)
        _save_checksum(dest)
        return dest, version
    except Exception as e:
        print(f"  ! Warning: Failed to create backup: {e}")
        return None, None


def archive_patch_file(patch_source_path, target_filepath, version_index):
    """
    Copies the patch file to .xtr/backup/.../target_file.version.patch
    This stores the patch alongside the backup of the file it modified.
    """
    if not patch_source_path:
        return
    try:
        # Calculate where the backup lives
        backup_dir, filename = _backup_location(target_filepath)
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Format: target.py.patch (v0), target.py.1.patch (v1)
        if version_index == 0:
            dest = backup_dir / (filename + ".patch")
        else:
            dest = backup_dir / (filename + f".{version_index}.patch")

        if not dest.exists():
            shutil.copy2(patch_source_path, dest)
            print(f"  (Patch archived to {dest})")

    except Exception as e:
        print(f"  ! Warning: Failed to archive patch file: {e}")


def save_log_file(log_content, target_filepath, version_index):
    """Saves the command output log."""
    try:
        backup_dir, filename = _backup_location(target_filepath)
        backup_dir.mkdir(parents=True, exist_ok=True)

        suffix = ".out" if version_index == 0 else f".{version_index}.out"
        dest = backup_dir / (filename + suffix)

        with open(dest, "w") as f:
            f.write(log_content)
    except Exception as e:
        print(f"  ! Warning: Failed to save log file: {e}")


def save_error_report(target_filepath, version_index, log_content):
    """Creates a combined error report with quintuple backticks."""
    try:
        backup_dir, filename = _backup_location(target_filepath)

        suffix_base = "" if version_index == 0 else f".{version_index}"

        orig_path = backup_dir / (filename + suffix_base + ".orig")
        patch_path = backup_dir / (filename + suffix_base + ".patch")

        report_path = backup_dir / (filename + suffix_base + ".rpterr")

        report = []

        # 1. Original
        report.append(f"Content of {orig_path.name}:")
        report.append("'''''")
        if orig_path.exists():
            report.append(orig_path.read_text())
        else:
            report.append("(File not found)")
        report.append("'''''\n")

        # 2. Patch
        report.append(f"Content of {patch_path.name}:")
        report.append("'''''")
        if patch_path.exists():
            report.append(patch_path.read_text())
        else:
            report.append("(File not found)")
        report.append("'''''\n")

        # 3. Output
        report.append(f"Output Log:")
        report.append("'''''")
        report.append(log_content)
        report.append("'''''\n")

        with open(report_path, "w") as f:
            f.write("\n".join(report))

        print(f"  ! Error Report generated: {report_path}")

    except Exception as e:
        print(f"  ! Warning: Failed to generate error report: {e}")


def revert_file(target_file):
    """Reverts the file to its most recent backup."""
    try:
        target = Path(target_file).resolve()
        backup_dir, filename = _backup_location(target)

        if not backup_dir.exists():
            print(f"No backups found for {target_file}")
            return

        backups = []
        base = backup_dir / (filename + ".orig")
        if base.exists():
            backups.append((0, base))

        for f in backup_dir.iterdir():
            if f.name.startswith(filename + ".") and f.name.endswith(".orig"):
                parts = f.name.split(".")
                if len(parts) >= 3 and parts[-2].isdigit():
                    idx = int(parts[-2])
                    backups.append((idx, f))

        if not backups:
            print(f"No backups found for {target_file}")
            return

        backups.sort(key=lambda x: x[0], reverse=True)
        latest_version, latest_backup = backups[0]

        print(f"Reverting {target_file}...")
        print(f"  Source: {latest_backup} (v{latest_version})")

        shutil.copy2(latest_backup, target)
        print("  ✓ File restored successfully.")

    except Exception as e:
        print(f"Error during revert: {e}")


def _apply_file_deletion(filepath, patch_source_path, output_fn, log_buffer):
    """Handle file deletion (empty search + empty replace)."""
    version = 0
    try:
        backup_path, version = create_backup(filepath)
        if backup_path and patch_source_path:
            archive_patch_file(patch_source_path, filepath, version)

        orig_len = 0
        try:
            with open(filepath, "r") as f:
                orig_len = len(f.readlines())
        except Exception:
            pass

        os.remove(filepath)
        try:
            _state_checksum_path(filepath).unlink(missing_ok=True)
        except Exception:
            pass
        output_fn(f"🗑️  {filepath} ... DELETED (Δ-{orig_len} lines)")
        save_log_file("\n".join(log_buffer), filepath, version)
    except Exception as e:
        output_fn(f"❌ {filepath} ... FAILED TO DELETE: {e}")
        save_log_file("\n".join(log_buffer), filepath, version)


def _is_whole_file_delete(block):
    """
    True for a whole-file delete: no search and nothing to put back.

    Covers `! DELETE FILE` and the legacy empty/empty block that doc/GEMINI.md
    still teaches. The hint is ignored here, matching the standalone deletion
    branch in apply_changes.
    """
    return not block["search"] and not block["replace"]


def _is_whole_file_create(block):
    """
    True for a create-file block: empty search with a body to write.

    A hint of 0 is the legacy spelling of "top of file" and means the same as
    no hint. Any later line is refused: you cannot insert at line 20 of a file
    the preceding hunk just deleted, so that pairing was not thought through.
    """
    return not block["search"] and bool(block["replace"]) and block["hint"] in (None, 0)


def _apply_file_creation(filepath, blocks, patch_source_path, output_fn, log_buffer):
    """Handle file creation (empty search, non-empty replace)."""
    version = 0
    try:
        new_content = "".join([l + "\n" for l in blocks[0]["replace"]])
        new_len = len(blocks[0]["replace"])

        backup_path, version = get_backup_path(Path(filepath), default_backup_root())
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.touch()

        if patch_source_path:
            archive_patch_file(patch_source_path, filepath, version)

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            f.write(new_content)

        _save_state_checksum(filepath)
        output_fn(f"✨ {filepath} ... CREATED (Δ+{new_len} lines)")
        save_log_file("\n".join(log_buffer), filepath, version)
    except Exception as e:
        output_fn(f"❌ {filepath} ... FAILED TO CREATE: {e}")
        save_log_file("\n".join(log_buffer), filepath, version)


def _apply_file_rewrite(filepath, blocks, patch_source_path, output_fn, log_buffer):
    """
    Handle whole-file replacement: `! DELETE FILE` followed by a create block.

    Two documented primitives composed to say "replace this file wholesale".
    Only this order is honoured. A lone create block against an existing file
    stays an error, because that shape is also what a block that simply lost
    its search text looks like, and truncating a file to the replace body on
    that guess would be destructive. The explicit delete states the intent.
    """
    version = 0
    try:
        new_lines = blocks[1]["replace"]
        new_content = "".join([l + "\n" for l in new_lines])

        orig_len = 0
        if os.path.exists(filepath):
            _verify_checksum(filepath)
            with open(filepath, "r") as f:
                orig_len = len(f.readlines())
            backup_path, version = create_backup(filepath)
            if backup_path is None:
                version = 0
        else:
            # Nothing to delete, so this degrades to a plain creation. Still
            # reserve the empty backup slot so --revert has a rung to land on.
            backup_path, version = get_backup_path(
                Path(filepath), default_backup_root()
            )
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.touch()

        if patch_source_path:
            archive_patch_file(patch_source_path, filepath, version)

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            f.write(new_content)

        _save_state_checksum(filepath)

        delta = len(new_lines) - orig_len
        sign = "+" if delta >= 0 else ""
        output_fn(f"♻️  {filepath} ... REWRITTEN (Δ{sign}{delta} lines)")
        save_log_file("\n".join(log_buffer), filepath, version)
    except Exception as e:
        output_fn(f"❌ {filepath} ... FAILED TO REWRITE: {e}")
        save_log_file("\n".join(log_buffer), filepath, version)


def _detect_conflicts(blocks, file_lines):
    """
    Pre-flight pass: resolve all block positions and check for overlapping ranges.
    Returns a set of block indices (1-based) that conflict with an earlier block.
    """
    resolved = []  # list of (1-based index, start, end)
    conflicts = set()

    for i, block in enumerate(blocks, 1):
        if not block["search"] and block["hint"] is not None:
            idx = max(0, block["hint"] - 1)
            match = (idx, idx)
        else:
            match = find_match(file_lines, block["search"], block["hint"])

        if match:
            start, end = match
            for prev_i, prev_start, prev_end in resolved:
                if start < prev_end and end > prev_start:
                    print(
                        f"  ⚠️  Conflict: Block {i} (lines {start + 1}-{end}) overlaps "
                        f"Block {prev_i} (lines {prev_start + 1}-{prev_end}). Block {i} will be skipped."
                    )
                    conflicts.add(i)
                    break
            else:
                resolved.append((i, start, end))

    return conflicts


def _process_hunks(file_lines, blocks):
    """Match and apply all hunks to file_lines in place. Returns (error_occurred, file_delta_total, hunk_stats)."""
    conflicts = _detect_conflicts(blocks, file_lines)

    error_occurred = False
    file_delta_total = 0
    hunk_stats = []

    for i, block in enumerate(blocks, 1):
        hunk_res = {"id": i, "annotation": block.get("annotation", "")}

        if block.get("malformed"):
            error_occurred = True
            hunk_res["status"] = "MALFORMED"
            hunk_res["detail"] = block["malformed"]
            hunk_res["patch_line"] = block.get("patch_line")
            hunk_stats.append(hunk_res)
            continue

        if i in conflicts:
            error_occurred = True
            hunk_res["status"] = "CONFLICT"
            hunk_stats.append(hunk_res)
            continue

        if not block["search"] and block["hint"] is not None:
            idx = max(0, block["hint"] - 1)
            match = (idx, idx)
        else:
            match = find_match(file_lines, block["search"], block["hint"])

        if match:
            start, end = match
            valid_match = True

            if block.get("tail"):
                norm_tail_block = [normalize(l) for l in block["tail"] if normalize(l)]
                if norm_tail_block:
                    current_file_idx = end
                    tail_idx = 0
                    while tail_idx < len(norm_tail_block):
                        if current_file_idx >= len(file_lines):
                            valid_match = False
                            break
                        norm_file = normalize(file_lines[current_file_idx])
                        if not norm_file:
                            current_file_idx += 1
                            continue
                        if norm_file != norm_tail_block[tail_idx]:
                            valid_match = False
                            break
                        current_file_idx += 1
                        tail_idx += 1

            if valid_match:
                new_lines = [l + "\n" for l in block["replace"]]
                file_lines[start:end] = new_lines

                rep_len = len(block["search"])
                new_len = len(block["replace"])
                delta = new_len - rep_len
                file_delta_total += delta

                hunk_res.update(
                    {
                        "status": "APPLIED",
                        "rep": rep_len,
                        "new": new_len,
                        "delta": delta,
                    }
                )
            else:
                error_occurred = True
                hunk_res["status"] = "BLOCKED"
        else:
            already_applied = find_match(file_lines, block["replace"])
            if already_applied:
                hunk_res["status"] = "SKIPPED"
            elif not block["search"] and block["hint"] is None:
                # No search text was ever supplied, so reporting "Block Not
                # Found" would describe a search that never ran. This is a
                # whole-file directive that landed on a path already on disk.
                error_occurred = True
                hunk_res["status"] = "EMPTY_SEARCH"
                hunk_res["detail"] = (
                    "Stray Delete Directive"
                    if not block["replace"]
                    else "Cannot Create, File Exists"
                )
            else:
                error_occurred = True
                hunk_res["status"] = "FAILED"
                hunk_res["hint"] = block["hint"]
                hunk_res["diagnosis"] = explain_match_failure(
                    file_lines, block["search"]
                )

        hunk_stats.append(hunk_res)

    return error_occurred, file_delta_total, hunk_stats


def _print_hunk_report(hunk_stats, file_delta_total, filepath, output_fn):
    """Print the per-file patch report."""
    successes = [h for h in hunk_stats if h["status"] == "APPLIED"]
    fails = [
        h
        for h in hunk_stats
        if h["status"] in ("FAILED", "BLOCKED", "EMPTY_SEARCH", "MALFORMED")
    ]

    if not fails and successes:
        file_icon = "✅ SUCCESS"
    elif not fails and not successes:
        file_icon = "⏭️  SKIPPED"
    elif fails and successes:
        file_icon = "⚠️  PARTIAL"
    else:
        file_icon = "❌ FAILED"

    sign = "+" if file_delta_total >= 0 else ""
    output_fn(f"📄 {filepath:<40} {file_icon} (Δ{sign}{file_delta_total} lines)")

    for h in hunk_stats:
        desc = f"@ {h['annotation']}" if h["annotation"] else f"Hunk {h['id']}"
        if len(desc) > 30:
            desc = desc[:27] + "..."

        if h["status"] == "APPLIED":
            d_sign = "+" if h["delta"] >= 0 else ""
            meta = f"[Rep: {h['rep']}, New: {h['new']}, Δ{d_sign}{h['delta']}]"
            line = f"   {h['id']}. ✅ {desc:<32} {meta}"
        elif h["status"] == "SKIPPED":
            line = f"   {h['id']}. 🧠 {desc:<32} [Already Applied]"
        elif h["status"] == "BLOCKED":
            line = f"   {h['id']}. 🛑 {desc:<32} [Tail Context Mismatch]"
        elif h["status"] == "CONFLICT":
            line = f"   {h['id']}. ⚡ {desc:<32} [Overlaps Earlier Block]"
        elif h["status"] == "EMPTY_SEARCH":
            line = f"   {h['id']}. ❌ {desc:<32} [{h['detail']}]"
        elif h["status"] == "MALFORMED":
            at = f" at patch line {h['patch_line']}" if h.get("patch_line") else ""
            line = f"   {h['id']}. 🧩 {desc:<32} [Unparseable: {h['detail']}{at}]"
        elif h["status"] == "FAILED":
            hint = f"~Line {h['hint']}" if h.get("hint") else "No Hint"
            line = f"   {h['id']}. ❌ {desc:<32} [Block Not Found] {hint}"
            if h.get("diagnosis"):
                line += f"\n      ↳ {h['diagnosis']}"

        output_fn(line)


def report_hunk_drift(content, changes, output_fn=print):
    """Warn when the parser produced fewer hunks than the patch text claims.

    The backstop for anything the structural rules miss. A hunk that goes
    missing is the one failure a writer cannot react to, because nothing in
    the report refers to it -- so the count is checked independently of how
    the parse actually went.
    """
    declared = count_hunk_openers(content)
    parsed = sum(len(blocks) for blocks in changes.values())
    if declared <= parsed:
        return 0
    missing = declared - parsed
    output_fn(
        f"  ⚠️  {missing} hunk(s) went missing: the patch opens {declared} "
        f"but only {parsed} could be read. Check for an unterminated block."
    )
    return missing


def check_changes(changes_dict, output_fn=print):
    """Dry-run every hunk against the files on disk without writing anything.

    Same matcher, same report, no backups and no edits: a model can find out
    whether a patch will land before anything is modified, which is cheaper
    than apply, discover a partial, revert, retry.
    """
    problems = 0
    for filepath, blocks in changes_dict.items():
        if not os.path.exists(filepath):
            malformed = [b for b in blocks if b.get("malformed")]
            creates = len(blocks) == 1 and not blocks[0]["search"] and not malformed
            if creates:
                output_fn(f"📄 {filepath:<40} ✅ WOULD CREATE")
            else:
                output_fn(f"📄 {filepath:<40} ❌ MISSING (cannot modify)")
                problems += 1
            continue

        try:
            with open(filepath, "r") as f:
                file_lines = f.readlines()
        except OSError as e:
            output_fn(f"📄 {filepath:<40} ❌ UNREADABLE: {e}")
            problems += 1
            continue

        # _process_hunks edits in place, so it runs against a throwaway copy.
        error_occurred, delta, hunk_stats = _process_hunks(list(file_lines), blocks)
        _print_hunk_report(hunk_stats, delta, filepath, output_fn)
        if error_occurred:
            problems += 1

    return problems


def apply_changes(changes_dict, patch_source_path=None):
    """Applies parsed changes to files."""
    for filepath, blocks in changes_dict.items():
        log_buffer = []

        def output(msg):
            print(msg)
            log_buffer.append(str(msg))

        # Every whole-file operation below is inferred from an empty search
        # block -- and an unparseable hunk leaves empty search AND empty
        # replace behind, which is exactly the delete signature. A patch
        # truncated mid-hunk is the ordinary result of a model running out of
        # tokens, and must never be read as "delete this file", so these paths
        # require the whole file's hunks to have parsed cleanly.
        malformed = [b for b in blocks if b.get("malformed")]

        if not malformed:
            # --- File Rewrite ---
            # `! DELETE FILE` plus a create block on one path. Both hunks land
            # in the same list, so without this they would fall through to the
            # modification path and fail as two searchless searches.
            if (
                len(blocks) == 2
                and _is_whole_file_delete(blocks[0])
                and _is_whole_file_create(blocks[1])
            ):
                _apply_file_rewrite(
                    filepath, blocks, patch_source_path, output, log_buffer
                )
                continue

            # --- File Deletion ---
            if os.path.exists(filepath):
                if (
                    len(blocks) == 1
                    and not blocks[0]["search"]
                    and not blocks[0]["replace"]
                ):
                    _apply_file_deletion(
                        filepath, patch_source_path, output, log_buffer
                    )
                    continue

            # --- File Creation ---
            if not os.path.exists(filepath):
                if (
                    len(blocks) == 1
                    and not blocks[0]["search"]
                    and not blocks[0]["replace"]
                ):
                    output(f"⏭️  {filepath} ... ALREADY ABSENT (nothing to delete)")
                    continue
                if len(blocks) == 1 and not blocks[0]["search"]:
                    _apply_file_creation(
                        filepath, blocks, patch_source_path, output, log_buffer
                    )
                    continue
                else:
                    output(f"❌ {filepath} ... NOT FOUND (Cannot modify missing file)")
                    continue

        if not os.path.exists(filepath):
            # Only reachable with unparseable hunks in hand: report them rather
            # than guessing at an intent the patch never managed to express.
            _, _, hunk_stats = _process_hunks([], blocks)
            _print_hunk_report(hunk_stats, 0, filepath, output)
            continue

        # --- Modification ---
        _verify_checksum(filepath)
        backup_path, version = create_backup(filepath)
        if backup_path and patch_source_path:
            archive_patch_file(patch_source_path, filepath, version)
        elif not backup_path:
            version = 0

        try:
            with open(filepath, "r") as f:
                file_lines = f.readlines()
        except Exception as e:
            output(f"❌ {filepath} ... ERROR READING: {e}")
            continue

        error_occurred, file_delta_total, hunk_stats = _process_hunks(
            file_lines, blocks
        )

        _print_hunk_report(hunk_stats, file_delta_total, filepath, output)

        save_log_file("\n".join(log_buffer), filepath, version)

        error_occurred = any(
            h["status"]
            in ("FAILED", "BLOCKED", "CONFLICT", "EMPTY_SEARCH", "MALFORMED")
            for h in hunk_stats
        )
        if error_occurred:
            save_error_report(filepath, version, "\n".join(log_buffer))

        successes = [h for h in hunk_stats if h["status"] == "APPLIED"]
        if successes:
            with open(filepath, "w") as f:
                f.writelines(file_lines)
        _save_state_checksum(filepath)


def main():
    parser = argparse.ArgumentParser(
        description="Apply AI-generated search/replace blocks",
        usage="%(prog)s [options] [target_file] [patch_file]",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {get_version()}"
    )

    parser.add_argument(
        "--revert", action="store_true", help="Revert file(s) to latest backup"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry run: report what the patch would do, without touching any file",
    )
    parser.add_argument(
        "args", nargs="*", help="File to revert, or Patch file to apply"
    )

    args = parser.parse_args()

    if not args.args:
        parser.print_help()
        sys.exit(1)

    for src_path, dest_path in migrate_legacy_state():
        print(f"  ↪ Moved {src_path.name} into {XTR_DIRNAME}/{dest_path.name}")

    if args.revert:
        target_candidate = args.args[0]
        if os.path.exists(target_candidate) and os.path.isfile(target_candidate):
            with open(target_candidate, "r") as f:
                try:
                    content = f.read()
                    if "--- a/" in content or "File: " in content:
                        changes = parse_multi_file_patch(content)
                        if changes:
                            print(
                                f"Found {len(changes)} target(s) in patch file to revert."
                            )
                            for filepath in changes.keys():
                                revert_file(filepath)
                            sys.exit(0)
                except UnicodeDecodeError:
                    pass
        revert_file(target_candidate)
        sys.exit(0)

    patch_path = None
    target_override = None

    if len(args.args) == 1:
        patch_path = args.args[0]
    elif len(args.args) == 2:
        target_override = args.args[0]
        patch_path = args.args[1]
    else:
        print("Error: Expected [target_file] patch_file (at most 2 arguments).")
        sys.exit(1)

    if not os.path.exists(patch_path):
        print(f"Error: File '{patch_path}' not found.")
        sys.exit(1)

    with open(patch_path, "r") as f:
        content = f.read()

    changes = parse_multi_file_patch(content, default_target=target_override)

    if not changes:
        print("No valid blocks found in patch file.")
        sys.exit(1)

    missing = report_hunk_drift(content, changes)

    if args.check:
        problems = check_changes(changes)
        total = sum(len(b) for b in changes.values())
        print(
            f"\nChecked {total} hunk(s) across {len(changes)} file(s). Nothing written."
        )
        sys.exit(1 if (problems or missing) else 0)

    apply_changes(changes, patch_source_path=patch_path)


if __name__ == "__main__":
    main()

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

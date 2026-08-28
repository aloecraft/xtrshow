#!/usr/bin/env python3

# ./xtrshow/cli.py
# License: Apache-2.0 (disclaimer at bottom of file)
"""
Interactive file tree selector for sharing code with LLMs

usage: xtrshow [-h] [--max-depth MAX_DEPTH] [--pattern PATTERN] [--ignore] [--no-ignore] [-o OUTFILE] [directory]

Interactive file tree selector

positional arguments:
  directory             Directory to browse (default: current directory)

options:
  -h, --help            show this help message and exit
  --max-depth MAX_DEPTH
                        Maximum depth to traverse
  --pattern PATTERN     Filter files by name pattern
  --ignore              Ignore common directories (node_modules, .git, etc.)
  --no-ignore           Show all files (disable default ignore patterns)
  -o OUTFILE, --outfile OUTFILE
                        Print output to file
  --no-meta             Omit the per-file '# meta:' line (size, line count,
                        modified/created dates, sha256)
  --no-hash             Omit only the sha256 digest from the '# meta:' line
---

Copyright [2026] [michael@aloecraft.org]

Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

import curses
import hashlib
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

from xtrshow import get_version


# Default ignore patterns
DEFAULT_IGNORE = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".env",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "dist",
    "build",
    ".egg-info",
    ".eggs",
    "target",
    ".idea",
    ".vscode",
}


class FileNode:
    def __init__(self, path, depth=0, is_last=False, parent=None):
        self.path = Path(path)
        self.depth = depth
        self.is_last = is_last
        self.selected = False
        self.is_dir = self.path.is_dir()
        self.parent = parent
        self.children = []
        self.expanded = False

    def get_display_line(self):
        """Generate the tree-style display line"""
        indent = "  " * self.depth
        prefix = "└─ " if self.is_last else "├─ "
        if self.depth == 0:
            prefix = ""

        checkbox = "[×]" if self.selected else "[ ]"

        # Show expand/collapse indicator for directories
        if self.is_dir:
            icon = "📂" if self.expanded else "📁"
            expand_indicator = "▼" if self.expanded else "▶"
            icon = f"{expand_indicator} {icon}"
        else:
            icon = "📄"

        name = self.path.name if self.depth > 0 else str(self.path)

        return f"{indent}{prefix}{checkbox} {icon} {name}"

    def get_size(self):
        """Get file size in bytes"""
        try:
            if self.is_dir:
                return 0
            return self.path.stat().st_size
        except Exception:
            return 0


def format_size(total_size):
    """Format a byte count as a human-readable string"""
    if total_size < 1024:
        return f"{total_size} B"
    elif total_size < 1024 * 1024:
        return f"{total_size / 1024:.1f} KB"
    elif total_size < 1024 * 1024 * 1024:
        return f"{total_size / (1024 * 1024):.1f} MB"
    else:
        return f"{total_size / (1024 * 1024 * 1024):.1f} GB"


def _format_timestamp(ts):
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def _creation_timestamp(st):
    """Best-effort file creation time, or None where the OS doesn't track it.

    st_birthtime exists on macOS and the BSDs; on Windows st_ctime is the
    creation time. On Linux st_ctime is inode-change time, not creation,
    so we return None rather than mislead.
    """
    birthtime = getattr(st, "st_birthtime", None)
    if birthtime is not None:
        return birthtime
    if sys.platform.startswith("win"):
        return st.st_ctime
    return None


def compute_sha256(path):
    """SHA256 of the file's raw bytes, or None if it can't be read.

    Deliberately hashes what is on disk rather than the CRLF-normalized,
    line-numbered text in the export block, so the digest matches both
    `sha256sum <file>` and the checksums xtrpatch records under .xtrpatch/.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def format_file_meta(path, line_count, include_hash=True):
    """Build the '# meta:' comment line for an exported file block.

    Starts with '#' so xtrpatch's parser treats it as noise if it ever
    round-trips through a patch file.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None

    parts = [
        format_size(st.st_size),
        f"{line_count} lines",
        f"modified {_format_timestamp(st.st_mtime)}",
    ]
    created = _creation_timestamp(st)
    if created is not None:
        parts.append(f"created {_format_timestamp(created)}")
    if include_hash:
        digest = compute_sha256(path)
        if digest is not None:
            parts.append(f"sha256 {digest}")

    return "# meta: " + " | ".join(parts)


def should_ignore(path, ignore_patterns):
    """Check if path should be ignored"""
    return path.name in ignore_patterns


def build_file_tree(root_path, max_depth=None, pattern=None, ignore_patterns=None):
    """Build a hierarchical tree of FileNode objects"""
    root = Path(root_path)

    if not root.exists():
        return None, 0

    if ignore_patterns is None:
        ignore_patterns = set()

    hidden_count = 0

    def build_node(path, depth, is_last=False, parent=None):
        nonlocal hidden_count

        if max_depth is not None and depth > max_depth:
            return None

        node = FileNode(path, depth, is_last, parent)

        if path.is_dir():
            try:
                entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            except PermissionError:
                return node

            filtered_entries = []
            for entry in entries:
                # Check ignore patterns
                if should_ignore(entry, ignore_patterns):
                    hidden_count += 1
                    continue

                # Apply name pattern filter
                if pattern and depth > 0:
                    if pattern not in entry.name:
                        continue

                filtered_entries.append(entry)

            for i, entry in enumerate(filtered_entries):
                is_last_entry = i == len(filtered_entries) - 1
                child = build_node(entry, depth + 1, is_last_entry, node)
                if child:
                    node.children.append(child)

        return node

    root_node = build_node(root, 0)
    root_node.expanded = True
    return root_node, hidden_count


def flatten_tree(root, visible_only=True):
    """Flatten the tree into a list for display"""
    nodes = []

    def walk(node):
        nodes.append(node)
        if node.is_dir and (node.expanded or not visible_only):
            for child in node.children:
                walk(child)

    if root:
        walk(root)
    return nodes


def select_all_in_directory(node, selected=True):
    """Recursively select/deselect all files in a directory"""
    count = 0
    if not node.is_dir:
        node.selected = selected
        return 1

    for child in node.children:
        count += select_all_in_directory(child, selected)

    return count


def get_selection_stats(root_node):
    """Get statistics about selected files"""
    all_nodes = flatten_tree(root_node, visible_only=False)
    selected_files = [n for n in all_nodes if n.selected and not n.is_dir]

    total_size = sum(n.get_size() for n in selected_files)

    return len(selected_files), format_size(total_size)


def show_confirmation(stdscr, selected_count, size_str):
    """Show confirmation dialog before exiting"""
    height, width = stdscr.getmaxyx()

    # Create a centered dialog box
    dialog_height = 7
    dialog_width = 50
    start_y = (height - dialog_height) // 2
    start_x = (width - dialog_width) // 2

    # Draw dialog
    dialog = curses.newwin(dialog_height, dialog_width, start_y, start_x)
    dialog.box()

    dialog.addstr(1, 2, "Confirm Complete?")
    dialog.addstr(3, 2, f"Exit and Print {selected_count} file(s) ({size_str})?")
    dialog.addstr(5, 2, "Y: Yes  |  N: No")

    dialog.refresh()

    # Wait for Y/N response
    while True:
        key = stdscr.getch()
        if key in (ord("y"), ord("Y")):
            return True
        elif key in (ord("n"), ord("N"), ord("q"), ord("Q"), 27):  # 27 is ESC
            return False


def main_curses(stdscr, root_node, hidden_count):
    """Main TUI loop using curses"""
    curses.curs_set(0)  # Hide cursor
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Highlight
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Selected
    curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)  # Status bar

    current_idx = 0
    scroll_offset = 0

    while True:
        # Get visible nodes
        nodes = flatten_tree(root_node, visible_only=True)

        # Get selection stats
        selected_count, size_str = get_selection_stats(root_node)

        stdscr.clear()
        height, width = stdscr.getmaxyx()
        visible_lines = height - 4  # Leave room for help text and status bar

        # Adjust scroll offset
        if current_idx >= len(nodes):
            current_idx = len(nodes) - 1
        if current_idx < 0:
            current_idx = 0

        if current_idx < scroll_offset:
            scroll_offset = current_idx
        elif current_idx >= scroll_offset + visible_lines:
            scroll_offset = current_idx - visible_lines + 1

        # Draw visible nodes
        for i in range(scroll_offset, min(scroll_offset + visible_lines, len(nodes))):
            node = nodes[i]
            line = node.get_display_line()

            # Truncate if too long
            if len(line) > width - 1:
                line = line[: width - 4] + "..."

            y_pos = i - scroll_offset

            if i == current_idx:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(y_pos, 0, line)
                stdscr.attroff(curses.color_pair(1))
            elif node.selected:
                stdscr.attron(curses.color_pair(2))
                stdscr.addstr(y_pos, 0, line)
                stdscr.attroff(curses.color_pair(2))
            else:
                stdscr.addstr(y_pos, 0, line)

        # Status bar
        status_y = height - 3
        stdscr.attron(curses.color_pair(3))
        status_left = f"Selected: {selected_count} files ({size_str})"
        if hidden_count > 0:
            status_right = f"{hidden_count} hidden"
            status_line = (
                status_left
                + " " * (width - len(status_left) - len(status_right) - 1)
                + status_right
            )
        else:
            status_line = status_left
        stdscr.addstr(status_y, 0, status_line[: width - 1])
        stdscr.attroff(curses.color_pair(3))

        # Help text
        help_text = "↑/↓: Navigate | ←/→: Collapse/Expand | SPC: Select | a/A: Select/Deselect All | p: Export | q: Quit"
        stdscr.addstr(height - 2, 0, "─" * min(width - 1, len(help_text)))
        stdscr.addstr(height - 1, 0, help_text[: width - 1])

        stdscr.refresh()

        # Handle input
        key = stdscr.getch()

        if key == curses.KEY_UP and current_idx > 0:
            current_idx -= 1
        elif key == curses.KEY_DOWN and current_idx < len(nodes) - 1:
            current_idx += 1
        elif key == curses.KEY_LEFT:
            # Collapse directory
            current_node = nodes[current_idx]
            if current_node.is_dir and current_node.expanded:
                current_node.expanded = False
            elif current_node.parent and current_node.depth > 0:
                # If already collapsed or is a file, jump to parent
                parent_idx = nodes.index(current_node.parent)
                current_idx = parent_idx
        elif key == curses.KEY_RIGHT:
            # Expand directory
            current_node = nodes[current_idx]
            if current_node.is_dir and not current_node.expanded:
                current_node.expanded = True
            elif (
                current_node.is_dir and current_node.expanded and current_node.children
            ):
                # If already expanded, jump to first child
                current_idx += 1
        elif key == ord(" "):  # Space to toggle selection
            nodes[current_idx].selected = not nodes[current_idx].selected
        elif key == ord("a"):  # Select all in current directory/file
            current_node = nodes[current_idx]
            if current_node.is_dir:
                select_all_in_directory(current_node, selected=True)
            else:
                current_node.selected = True
        elif key == ord("A"):  # Deselect all in current directory/file
            current_node = nodes[current_idx]
            if current_node.is_dir:
                select_all_in_directory(current_node, selected=False)
            else:
                current_node.selected = False
        elif key in (ord("q"), ord("Q")):  # Quit without output
            return None
        elif key in (ord("p"), ord("P"), ord("\n"), curses.KEY_ENTER, 10, 13):
            if selected_count == 0:
                continue  # No files selected, do nothing

            # Show confirmation
            if show_confirmation(stdscr, selected_count, size_str):
                all_nodes = flatten_tree(root_node, visible_only=False)
                selected_files = [n for n in all_nodes if n.selected and not n.is_dir]
                return [str(node.path) for node in selected_files]
            else:
                continue  # Return to tree view


def main():
    parser = argparse.ArgumentParser(description="Interactive file tree selector")
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {get_version()}"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to browse (default: current directory)",
    )
    parser.add_argument(
        "--max-depth", type=int, default=None, help="Maximum depth to traverse"
    )
    parser.add_argument(
        "--pattern", type=str, default=None, help="Filter files by name pattern"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Omit line number prefixes (print raw file content)",
    )
    parser.add_argument(
        "--ignore",
        action="store_true",
        help="Ignore common directories (node_modules, .git, etc.)",
    )
    parser.add_argument(
        "--no-ignore",
        action="store_true",
        help="Show all files (disable default ignore patterns)",
    )
    parser.add_argument(
        "-o", "--outfile", type=str, default=None, help="Print output to file"
    )
    parser.add_argument(
        "--multi",
        nargs="?",
        const=".xtrshow",
        default=None,
        metavar="DIR",
        help="Output individual files to directory (default: .xtrshow)",
    )
    parser.add_argument(
        "--update",
        "-u",
        action="store_true",
        help="Re-export previously selected files from .xtrshow_manifest without launching TUI",
    )
    parser.add_argument(
        "--prompt",
        "-p",
        action="store_true",
        help="Print the LLM prompting instructions and exit",
    )
    parser.add_argument(
        "--no-meta",
        action="store_true",
        help="Omit the per-file '# meta:' line (size, line count, modified/created dates, sha256)",
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="Omit only the sha256 digest from the '# meta:' line",
    )

    args = parser.parse_args()

    if args.prompt:
        prompt_path = Path(__file__).parent / "assets" / "llm_prompt.md"
        try:
            print(prompt_path.read_text())
        except FileNotFoundError:
            print(f"Error: prompt file not found at {prompt_path}", file=sys.stderr)
            sys.exit(1)
        return

    if args.outfile:
        directory = os.path.dirname(args.outfile) or "."
        if not os.access(directory, os.W_OK):
            print(f"Directory '{directory}' is not writable. Cannot create file.")
            return

    # Determine ignore patterns
    if args.no_ignore:
        ignore_patterns = set()
    elif args.ignore:
        ignore_patterns = DEFAULT_IGNORE
    else:
        # Default: use ignore patterns
        ignore_patterns = DEFAULT_IGNORE

    # Build the file tree
    root_node, hidden_count = build_file_tree(
        args.directory, args.max_depth, args.pattern, ignore_patterns
    )

    if not root_node:
        print(f"Error: Could not read directory '{args.directory}'", file=sys.stderr)
        sys.exit(1)

    MANIFEST_PATH = Path(".xtrshow_manifest")

    # Run the TUI (or load manifest for --update)
    try:
        if args.update:
            if not MANIFEST_PATH.exists():
                print(
                    "Error: No .xtrshow_manifest found. Run xtrshow normally first to create one.",
                    file=sys.stderr,
                )
                sys.exit(1)
            result = [l for l in MANIFEST_PATH.read_text().splitlines() if l.strip()]
            if not result:
                print("Error: .xtrshow_manifest is empty.", file=sys.stderr)
                sys.exit(1)
            print(f"Updating {len(result)} file(s) from manifest...", file=sys.stderr)
        else:
            result = curses.wrapper(main_curses, root_node, hidden_count)

        if result is not None:
            # Save manifest after a fresh TUI selection
            if not args.update:
                MANIFEST_PATH.write_text("\n".join(result) + "\n")

            output = []
            multi_dir = None

            if args.multi:
                multi_dir = Path(args.multi)
                try:
                    multi_dir.mkdir(parents=True, exist_ok=True)
                    print(f"Saving individual files to: {multi_dir}", file=sys.stderr)
                except Exception as e:
                    print(f"Error creating directory {multi_dir}: {e}", file=sys.stderr)
                    return

            for path in result:
                try:
                    with open(path, "r") as f:
                        content = f.read().replace("\r\n", "\n")
                        root_ext = os.path.splitext(path)
                        file_extension = root_ext[1]

                        lines = content.splitlines()

                        if not args.clean:
                            max_ln_width = len(str(len(lines)))
                            formatted_content = "\n".join(
                                f"{i + 1:>{max_ln_width}}:{line}"
                                for i, line in enumerate(lines)
                            )
                        else:
                            formatted_content = content

                        meta_line = ""
                        if not args.no_meta:
                            meta = format_file_meta(
                                path, len(lines), include_hash=not args.no_hash
                            )
                            if meta:
                                meta_line = meta + "\n"

                        # We construct the block using concatenation to avoid confusing LLM parsers
                        # when this file is pasted into prompts.
                        code_fence = "```"
                        block = f"""
--- a/{path}
+++ b/{path}
{meta_line}{code_fence} {file_extension[1:] if file_extension.startswith(".") else file_extension}
{formatted_content}
{code_fence}
"""
                        if multi_dir:
                            # Replace path separators with double underscore for flat filename
                            safe_name = path.replace(os.sep, "__") + ".xtr.md"
                            out_path = multi_dir / safe_name
                            with open(out_path, "w") as out_f:
                                out_f.write(block.strip())
                        else:
                            output.append(block)

                except (IOError, UnicodeDecodeError) as e:
                    print(f"# File: {path} (Error: {e})", file=sys.stderr)

            if not multi_dir:
                final_output = "\n".join(output)
                if args.outfile:
                    with open(args.outfile, "w") as outfile:
                        outfile.write(final_output)
                else:
                    print(final_output)
            else:
                print(f"hint:\n\tcd {multi_dir}\n")
                print('hint:\n\tfor file in *; do mv "$file" "r1_${file}"; done')

    except KeyboardInterrupt:
        pass


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

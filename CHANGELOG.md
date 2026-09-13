# Changelog

All notable changes to xtrshow are recorded here.

Generated from `CHANGELOG.yaml`, which is the source of truth --
edit that file, then run `technoproj-changelog generate`.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.3.0] - 2026-08-29

`v1.3.0`

All project state moves under one `.xtr/` directory. Both commands
migrate a pre-1.3 layout on their first run, so no user action is
required and this is a minor rather than a major.

### Added

- Automatic migration on the first run of either command. Each entry
  moves only when its `.xtr/` counterpart does not already exist, so
  the migration is idempotent, resumable and cannot clobber existing
  state. Backups move rather than being left behind: stranding them
  under `.xtrpatch/` would silently break `--revert` for anyone with
  history.

### Changed

- `.xtrshow_manifest` is now `.xtr/manifest`, `.xtrpatch/` is now
  `.xtr/backup/`, and `.xtrshow/` is now `.xtr/multi/`. The backup
  tree keeps its own subdirectory rather than sitting at the root, so
  a project path named `manifest` or `multi` cannot collide with the
  state files.
- `.gitignore` collapses to `.xtr*`, covering the new directory and
  both legacy names.


## [1.2.0] - 2026-08-28

`v1.2.0`

Exported file blocks carry a SHA-256 digest, so a model reading the
context can tell whether it has already seen a file rather than
re-reading it to find out.

### Added

- A `sha256` field in each block's `# meta:` line. The digest covers
  the file's raw bytes on disk rather than the newline-normalized and
  line-numbered text inside the fence, so it equals both
  `sha256sum <file>` and the checksums xtrpatch already records. A
  failed digest read drops the field rather than the whole meta line.
- `--no-hash`, which keeps the meta line and omits just the digest.
  `--no-meta` still omits the line entirely.

### Changed

- The LLM prompt asset now describes the export format it reads, not
  only the patch format it writes. The costly omission predates the
  digest: content lines carry an `N:` line-number prefix and
  `normalize()` strips only whitespace, so a search block that keeps
  the prefix fails with "Block Not Found".


## [1.1.0] - 2026-08-25

`v1.1.0`

Per-file metadata in exports, and whole-file replacement by composing
the two primitives that already existed.

### Added

- A `# meta:` line under each exported file header carrying size, line
  count and modification date, plus creation date on platforms that
  track it. Linux exposes only inode-change time, so it is omitted
  there. The line starts with `#`, which xtrpatch's parser skips, so
  exports stay round-trip safe. Disable with `--no-meta`.
- Whole-file replacement via `! DELETE FILE` followed by a create
  block. Only delete-then-create is honoured: a lone create block
  against an existing file stays an error, because that shape is also
  what a hunk whose search text went missing looks like, and
  truncating the file on that guess would throw work away.

### Changed

- `get_version` moved to the package root so `repatch.py` no longer
  imports `cli.py`, which imports curses at module scope. The patcher
  now needs nothing beyond the standard library and runs on a
  curses-less interpreter.

### Fixed

- Absolute paths are handled correctly by xtrpatch.
- Hunks carrying no search block no longer report "Block Not Found",
  which described a search that never ran. They now report "Stray
  Delete Directive" or "Cannot Create, File Exists".


## [1.0.1] - 2026-07-25

`v1.0.1`

A version flag and shorter names for both commands.

### Added

- `-v` / `--version` on both xtrshow and xtrpatch.
- `xtsh` and `xtpa`, short aliases for `xtrshow` and `xtrpatch`.


## [1.0.0] - 2026-07-09

`v1.0.0`

The first release declared stable.

### Changed

- Checksum handling updated.
- An expanded README and getting-started guide.

### Fixed

- Argparse stability fixes.
- Empty files are handled correctly rather than treated as missing.


## [0.3.1] - 2026-06-30

`v0.3.1`

The LLM prompt becomes printable, and the docs become generated.

### Added

- `-p` / `--prompt`, which prints the bundled LLM prompt to stdout.
- `script/pydocgen.py`, a documentation generator, driven by the
  `docgen` make target.


## [0.3.0] - 2026-06-27

`v0.3.0`

Conflict detection, an update shortcut, and the first release
published by workflow rather than by hand.

### Added

- Checksum and block conflict detection in xtrpatch.
- `-u` / `--update`, a shortcut for re-exporting the last selection.
- Wildcard anchoring in the delete syntax.
- A GitHub Actions workflow that publishes to PyPI on a `v*` tag.
  Every earlier upload was made by hand, which is why the tags and the
  PyPI versions before this one do not correspond.

### Changed

- `apply_changes` refactored.

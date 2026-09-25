# Contributing to Meso Mode

Thanks for helping. Meso Mode is free and open source, and will stay non-commercial.

## Sign your commits (DCO)
Every commit must carry a `Signed-off-by:` line (`git commit -s`). It certifies the
[Developer Certificate of Origin 1.1](https://developercertificate.org/): you wrote the change,
or have the right to submit it under the project's licences.

## Licences
- Code: GPL-3.0-or-later. New source files start with
  `# SPDX-License-Identifier: GPL-3.0-or-later`.
- Documentation and media: CC-BY-SA-4.0 (see `REUSE.toml`).

## Clean-room rules
- **Never commit third-party material:** screenshots or recordings of other applications,
  their icons, artwork, sampled colours, documentation text, scripts or configuration. Describe
  behaviour in your own words instead. Blender's own GPL sources and docs may be referenced.
- Design from public sources only (Blender docs and source, published papers, expired
  patents). Don't decompile or extract anything from other software.
- Never implement multi-touch finger-chord gesture recognition; a live third-party patent
  covers it.
- The only places that may name another DCC are the README's "coming from" sentence, its
  non-affiliation notice and `docs/comparison.md`.

## Behaviour rules
- Never erase a native Blender feature. Meso Mode adds or relocates, every displaced action
  stays reachable, and every Meso binding can be switched off.
- Plaza controls mirror the native control they stand for, including click and modifier
  conventions.

## Before you open a pull request
Follow `CLAUDE.md` and run the unit tests, the headless Blender tests and
`extension validate` (commands in the README), plus the GUI suite for UI changes. Every
Blender launch must use fresh `BLENDER_USER_CONFIG` / `BLENDER_USER_EXTENSIONS` directories.

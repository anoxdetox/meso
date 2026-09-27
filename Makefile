# SPDX-License-Identifier: GPL-3.0-or-later
# Build, test and check the Meso Mode extension (GNU make; `make` alone prints the targets).
#
# Every Blender launch goes through tools/env.sh (B = the Blender binary, PY = its Python; set
# them in an untracked local.env) and $(BLENDER): no desktop (DISPLAY, WAYLAND_DISPLAY and the
# session bus unset, a private XDG_RUNTIME_DIR), a 1-byte core limit (a crash never reaches the
# desktop's crash reporter) and fresh temporary BLENDER_USER_CONFIG / BLENDER_USER_EXTENSIONS
# folders, removed afterwards. Windows: use the raw commands in CONTRIBUTING.md.
#
#   make test K=pattern       only the headless tests matching the pattern
#   make gui GUI_ARGS="--only gif"
#   make profile PROFILE_ARGS="-n 50 --only object,edit_mesh --detail"
#   make release              the release's checks and plan (nothing is tagged or pushed)
#   make release CONFIRM=v0.7.1 [DRAFT=1]   tag, push and publish the GitHub release

SHELL := bash
.DEFAULT_GOAL := help

MANIFEST := src/meso/blender_manifest.toml
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' $(MANIFEST))
DIST := dist
ZIP := $(DIST)/meso-$(VERSION).zip
K ?=
GUI_ARGS ?=
PROFILE_ARGS ?=
TAG := v$(VERSION)
REMOTE ?= origin
BRANCH ?= master
CONFIRM ?=
DRAFT ?=
# The release notes: the "## <version>" section of CHANGELOG.md.
NOTES = awk '/^\#\# /{on = ($$2 == "$(VERSION)")} on' CHANGELOG.md | tail -n +2

# The shell prologue of every recipe that runs Blender: stop on the first error, B / PY, a
# temporary folder $$T (removed on exit) with the private runtime, config and extensions
# folders, and the 1-byte core limit for this shell and everything it starts.
PROLOGUE = set -eo pipefail; . tools/env.sh; T="$$(mktemp -d)"; trap 'rm -rf "$$T"' EXIT; \
	mkdir -m 700 "$$T/run" "$$T/cfg" "$$T/ext"; \
	prlimit --core=1 --pid $$$$ >/dev/null 2>&1 || ulimit -c 0
# Blender without the desktop, on the folders of $$T (use after $(PROLOGUE)).
BLENDER = env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
	XDG_RUNTIME_DIR="$$T/run" BLENDER_USER_CONFIG="$$T/cfg" BLENDER_USER_EXTENSIONS="$$T/ext" "$$B"
HEADLESS_TESTS = --factory-startup --python-exit-code 1 --python tests/run_tests.py --

# `make check`: the installed add-on must be enabled and registered at start-up, then unregister
# and register again cleanly (headless; the first-enable keymap question needs a timer, which
# never fires in -b).
ADDON := bl_ext.user_default.meso
CHECK_EXPR = import addon_utils, bpy; m = '$(ADDON)'; \
	ops = lambda: [n for n in dir(bpy.types) if n.startswith('MESO_')]; \
	meso_items = lambda: [i.idname for c in (bpy.context.window_manager.keyconfigs.addon,) if c for k in c.keymaps for i in k.keymap_items if i.idname.startswith('meso.')]; \
	assert addon_utils.check(m) == (True, True), ('not enabled at start-up', addon_utils.check(m)); \
	assert 'MESO_OT_plaza' in ops() and bpy.context.preferences.addons.get(m), 'not registered'; \
	assert meso_items(), 'no Plaza keymap items'; n = len(ops()); \
	addon_utils.disable(m, default_set=True); \
	assert addon_utils.check(m)[1] is False and ops() == [] and meso_items() == [], ('unregister left', ops(), meso_items()); \
	addon_utils.enable(m, default_set=True); \
	assert addon_utils.check(m) == (True, True) and len(ops()) == n, ('re-enable', ops()); \
	addon_utils.disable(m, default_set=True); \
	assert ops() == [] and meso_items() == [], 'second unregister'; \
	print('check: meso', bpy.app.version_string, n, 'classes registered and unregistered cleanly')

.PHONY: help version test-unit test test-render validate build check gui persist profile all \
	clean dev-link dev-unlink notes release-check release

help: ## Show this list
	@echo "Meso Mode $(VERSION): make <target>"
	@awk 'BEGIN { FS = ":.*## " } /^[a-z][a-z-]*:.*## / { printf "  %-14s %s\n", $$1, $$2 }' \
		$(MAKEFILE_LIST)

version: ## Print the manifest version
	@echo $(VERSION)

test-unit: ## Pure Python unit tests (no Blender)
	@. tools/env.sh; "$${PY:-python3}" -m unittest discover -s tests/unit -t .

test: ## Headless Blender tests (K=pattern for a subset)
	@$(PROLOGUE); $(BLENDER) -b $(HEADLESS_TESTS) $(if $(K),-k '$(K)')

test-render: ## Offscreen render tests on Vulkan and OpenGL
	@$(PROLOGUE); for backend in vulkan opengl; do echo "== $$backend"; \
		$(BLENDER) -b --gpu-backend $$backend $(HEADLESS_TESTS) -k test_render_offscreen; done

validate: ## Validate the extension source (src/meso)
	@$(PROLOGUE); $(BLENDER) --command extension validate src/meso

build: ## Build dist/meso-<version>.zip
	@$(PROLOGUE); mkdir -p $(DIST); rm -f $(ZIP); \
		$(BLENDER) --command extension build --source-dir src/meso --output-dir $(DIST); \
		test -f $(ZIP)

check: build ## Validate, inspect, install and enable the built zip (headless)
	@$(PROLOGUE); echo "== validate $(ZIP)"; $(BLENDER) --command extension validate $(ZIP); \
		echo "== content"; "$${PY:-python3}" tools/check_zip.py $(ZIP) --version $(VERSION); \
		echo "== install into a temporary user_default"; \
		$(BLENDER) --command extension install-file -r user_default -e $(ZIP); \
		test -f "$$T/ext/user_default/meso/blender_manifest.toml"; \
		echo "== enable, unregister, register"; \
		$(BLENDER) -b --python-exit-code 1 --python-expr "$(CHECK_EXPR)" 2>&1 | tee "$$T/check.log"; \
		if grep -q '^Traceback' "$$T/check.log"; then echo "check: a traceback in the log" >&2; exit 1; fi; \
		echo "check: $(ZIP) OK"

gui: ## GUI suite in a nested session (Linux; GUI_ARGS="--only a,b")
	@. tools/env.sh; T="$$(mktemp -d)"; trap 'rm -rf "$$T"' EXIT; \
		BLENDER_USER_CONFIG="$$T/cfg" BLENDER_USER_EXTENSIONS="$$T/ext" \
		timeout 700 tests/gui/run_gui_tests.sh $(GUI_ARGS)

persist: ## Meso Keymap restart check in a nested session (Linux)
	@. tools/env.sh; T="$$(mktemp -d)"; trap 'rm -rf "$$T"' EXIT; \
		BLENDER_USER_CONFIG="$$T/cfg" BLENDER_USER_EXTENSIONS="$$T/ext" \
		timeout 400 tests/gui/run_persist_check.sh

profile: ## Time the Plaza's hot paths (headless; PROFILE_ARGS="-n 50 --only object")
	@$(PROLOGUE); $(BLENDER) -b --factory-startup --python-exit-code 1 \
		--python tools/profile_plaza.py -- $(PROFILE_ARGS)

all: test-unit test validate build check ## Unit + headless tests, validate, build, check

clean: ## Remove dist/ and every __pycache__
	rm -rf $(DIST)
	find src tests tools -name __pycache__ -type d -prune -exec rm -rf {} +

dev-link: ## Link src/meso into MESO_EXTENSIONS_DIR for development
	python3 tools/dev_link.py

dev-unlink: ## Remove the development link (then install the zip to test the real package)
	python3 tools/dev_link.py --remove

notes: ## Print the release notes of this version (from CHANGELOG.md)
	@notes="$$($(NOTES))"; test -n "$$notes" || { echo "no '## $(VERSION)' in CHANGELOG.md" >&2; exit 1; }; \
		echo "$$notes"

# The release's preconditions (every one is checked; any failure stops): a clean tree on
# $(BRANCH), the tag not taken yet (here or on $(REMOTE)), release notes for the version, the gh
# CLI logged in, and the private pre-push scan (local/release-check.sh, when there is one).
release-check: ## Check that this version can be released (read-only)
	@set -eo pipefail; ok=1; fail() { echo "  ✗ $$*"; ok=0; }; pass() { echo "  ✓ $$*"; }; \
	echo "Meso Mode $(VERSION): release $(TAG) from $(BRANCH) to $(REMOTE)"; \
	[ -z "$$(git status --porcelain)" ] && pass "clean tree" || fail "uncommitted changes"; \
	[ "$$(git rev-parse --abbrev-ref HEAD)" = "$(BRANCH)" ] && pass "on $(BRANCH)" \
		|| fail "not on $(BRANCH) ($$(git rev-parse --abbrev-ref HEAD))"; \
	! git rev-parse -q --verify "refs/tags/$(TAG)" >/dev/null && pass "no local tag $(TAG)" \
		|| fail "the tag $(TAG) exists here"; \
	git fetch -q --tags $(REMOTE) 2>/dev/null || fail "cannot reach $(REMOTE)"; \
	! git ls-remote --exit-code --tags $(REMOTE) "refs/tags/$(TAG)" >/dev/null 2>&1 \
		&& pass "no tag $(TAG) on $(REMOTE)" || fail "the tag $(TAG) exists on $(REMOTE)"; \
	[ -n "$$($(NOTES))" ] && pass "release notes in CHANGELOG.md" || fail "no '## $(VERSION)' in CHANGELOG.md"; \
	if command -v gh >/dev/null; then gh auth status >/dev/null 2>&1 && pass "gh logged in" \
		|| fail "gh is not logged in (gh auth login)"; else fail "no gh CLI (GitHub CLI: https://cli.github.com)"; fi; \
	if [ -x local/release-check.sh ]; then local/release-check.sh "$(REMOTE)/$(BRANCH)..HEAD" >/dev/null 2>&1 \
		&& pass "pre-push scan clean" || fail "pre-push scan: run local/release-check.sh"; fi; \
	[ $$ok = 1 ] || { echo "release-check: not ready"; exit 1; }; echo "release-check: ready"

# `make release`: the checks and the plan. `make release CONFIRM=$(TAG)`: the checks, `make all`,
# then tag, push and publish; DRAFT=1 makes the GitHub release a draft (published by hand on
# the release page). Going public (the repository's visibility, the extensions platform
# upload) stays by hand.
release: ## Release checks and plan; CONFIRM=v<version> [DRAFT=1] tags, pushes and publishes
	@$(MAKE) --no-print-directory release-check
	@if [ "$(CONFIRM)" != "$(TAG)" ]; then \
		echo; echo "Plan for $(TAG) (run: make release CONFIRM=$(TAG) [DRAFT=1]):"; \
		echo "  1. make all                        unit + headless tests, validate, build, check"; \
		echo "  2. git tag -a $(TAG)                annotated, on $$(git rev-parse --short HEAD)"; \
		echo "  3. git push $(REMOTE) $(BRANCH) $(TAG)"; \
		echo "  4. gh release create $(TAG) $(ZIP)  notes: make notes$(if $(DRAFT), (draft))"; \
		echo "By hand afterwards: make the repository public, upload $(ZIP) to extensions.blender.org."; \
		echo "Also run before: make test-render, make gui, make persist."; \
		exit 0; fi; \
	set -eo pipefail; \
	$(MAKE) --no-print-directory all; \
	git tag -a "$(TAG)" -m "Meso Mode $(VERSION)"; \
	git push $(REMOTE) $(BRANCH) "$(TAG)"; \
	mkdir -p $(DIST); $(NOTES) > "$(DIST)/notes-$(VERSION).md"; \
	gh release create "$(TAG)" "$(ZIP)" --verify-tag --title "Meso Mode $(VERSION)" \
		--notes-file "$(DIST)/notes-$(VERSION).md" $(if $(DRAFT),--draft); \
	echo "release: $(TAG) published$(if $(DRAFT), as a draft)"

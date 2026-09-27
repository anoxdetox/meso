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

SHELL := bash
.DEFAULT_GOAL := help

MANIFEST := src/meso/blender_manifest.toml
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' $(MANIFEST))
DIST := dist
ZIP := $(DIST)/meso-$(VERSION).zip
K ?=
GUI_ARGS ?=

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
	clean dev-link release

help: ## Show this list
	@echo "Meso Mode $(VERSION): make <target>"
	@awk 'BEGIN { FS = ":.*## " } /^[a-z][a-z-]*:.*## / { printf "  %-12s %s\n", $$1, $$2 }' \
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

profile: ## Time the Plaza's hot paths (headless)
	@. tools/env.sh; test -f tools/profile_plaza.py || { echo "tools/profile_plaza.py is missing" >&2; exit 1; }; \
		"$${PY:-python3}" tools/profile_plaza.py

all: test-unit test validate build check ## Unit + headless tests, validate, build, check

clean: ## Remove dist/ and every __pycache__
	rm -rf $(DIST)
	find src tests tools -name __pycache__ -type d -prune -exec rm -rf {} +

dev-link: ## Link src/meso into MESO_EXTENSIONS_DIR for development
	python3 tools/dev_link.py

release: ## Print the release checklist (nothing is run)
	@echo "Release checklist for Meso Mode $(VERSION):"
	@echo "  1. version = \"$(VERSION)\" in $(MANIFEST) is the release version, committed"
	@echo "  2. make all                  (unit + headless tests, validate, build, check)"
	@echo "  3. make test-render          (offscreen renderer on Vulkan and OpenGL)"
	@echo "  4. make gui && make persist  (nested GUI suite and restart check, Linux)"
	@echo "  5. git tag -a v$(VERSION) -m \"Meso Mode $(VERSION)\"   (by hand)"
	@echo "  6. push master and the tag   (by hand)"
	@echo "  7. upload $(ZIP) to the release page / extensions platform (by hand)"

PYTHON ?= .venv/bin/python
DISPLAY_PANEL ?= MIP_Sharp_mono_400x240
SCALE ?=
SCALE_ARG = $(if $(SCALE),--emulate-scale $(SCALE))
GPX ?=
NAME ?= $(basename $(notdir $(GPX)))
DEPS = PyQt6 numpy cython pillow pyqtgraph fitparse oyaml polyline aiohttp qasync psutil

.DEFAULT_GOAL := help

.PHONY: ridden-roads deploy
.PHONY: mapsforge-deps
.PHONY: mapsforge-up mapsforge-down map-render
.PHONY: help venv emulate emulate-real-size demo keys gpx use-course courses test-course reset-demo

help:
	@echo "Targets:"
	@echo "  make venv                  create .venv and install desktop dependencies"
	@echo "  make emulate [SCALE=N]     demo ride on emulated $(DISPLAY_PANEL) (auto scale)"
	@echo "  make emulate-real-size     emulator at x1 screen pixels (close to physical size on HiDPI)"
	@echo "  make demo                  demo ride in the plain colour Qt window"
	@echo "  make keys                  emulator keyboard reference"
	@echo "  make gpx GPX=path.gpx      convert GPX to courses/<name>.tcx and make it active"
	@echo "  make use-course NAME=x     activate courses/x.tcx"
	@echo "  make courses               list course files"
	@echo "  make test-course           build the Ventoux test loop (needs network)"
	@echo "  make reset-demo            forget recorded demo positions so the course is replayed"
	@echo "  make ridden-roads          build rides/ridden_roads.npz from rides/gpx/*.gpx (Map Overlay > Ridden roads)"
	@echo "  make mapsforge-deps MAP_FILE=x.map  fetch renderer + Elevate theme, copy OpenAndroMaps .map"
	@echo "  make mapsforge-up          start local Mapsforge tile server in Docker (needs tools/mapsforge/vendor)"
	@echo "  make mapsforge-down        stop it"
	@echo "  make map-render NAME=x BBOX=s,w,n,e [TASK=mono|elevate] [ZOOMS=11-16] [PAD_KM=3]"
	@echo "                             render maptile/x.mbtiles (add x to map.yaml with use_mbtiles: true)"
	@echo "  make deploy PI=user@host   rsync maps, ridden roads and courses to the Pi (code goes via git)"
	@echo "Variables: DISPLAY_PANEL=$(DISPLAY_PANEL) (or MIP_Sharp_mono_320x240), PYTHON=$(PYTHON)"

venv:
	uv venv --python 3.13 .venv
	uv pip install --python $(PYTHON) $(DEPS)

emulate:
	$(PYTHON) pizero_bikecomputer.py --demo --emulate-display $(DISPLAY_PANEL) $(SCALE_ARG)

emulate-real-size:
	$(MAKE) emulate SCALE=1

demo:
	$(PYTHON) pizero_bikecomputer.py --demo

keys:
	@echo "Emulator keys (window must have focus):"
	@echo "  A..E        hardware buttons, Shift+key = long press"
	@echo "  [ / ]       mono_cutoff -8 / +8 (sharp-drm default 32, try ~188)"
	@echo "  \\           toggle 4x4 Bayer dithering (sharp-drm dither_algo=1)"
	@echo "  P           save frame to screenshots/: *_mono.png (exact 1-bit) and *_lcd.png"
	@echo ""
	@echo "Five-button layout:"
	@echo "  data pages  A prev page / long: colour screenshot   B lap / long: reset"
	@echo "              C multiscan (ANT+ only)   D start-stop   E next page / long: menu"
	@echo "  map page    A prev page   B zoom out   C overlays / long: move mode"
	@echo "              D zoom in     E next page (no menu here)"
	@echo "  menu        A back   B brightness   C select   D up   E down"

gpx:
	@test -n "$(GPX)" || (echo "usage: make gpx GPX=~/Downloads/track.gpx [NAME=name]" && exit 1)
	python3 -I tools/gpx_to_tcx.py "$(GPX)" "courses/$(NAME).tcx"
	$(MAKE) use-course NAME="$(NAME)"

use-course:
	@test -f "courses/$(NAME).tcx" || (echo "courses/$(NAME).tcx not found" && exit 1)
	cp "courses/$(NAME).tcx" courses/.current
	$(MAKE) reset-demo

courses:
	@find courses -maxdepth 1 \( -name "*.tcx" -o -name "*.fit" \) | sort

test-course:
	python3 -I tools/make_test_course.py --name "Ventoux loop" --spacing 40 \
		--output courses/ventoux_loop.tcx \
		44.1245,5.1797 44.1741,5.2786 44.1738,5.1322 44.1245,5.1797

reset-demo:
	rm -f log/log.db

MAPSFORGE_CONTAINER = pizero-mapsforge
MAPSFORGE_VENDOR = tools/mapsforge/vendor
MAPSFORGESRV_VERSION ?= v0.30.0.1
MAP_FILE ?=
TASK ?= mono
ZOOMS ?= 11-16
PAD_KM ?= 3
BBOX ?=
ONE_BIT = $(if $(filter mono,$(TASK)),--one-bit 128)

mapsforge-deps:
	@test -n "$(MAP_FILE)" || (echo "usage: make mapsforge-deps MAP_FILE=~/Downloads/Cyprus_oam.osm.map (from openandromaps.org)" && exit 1)
	mkdir -p $(MAPSFORGE_VENDOR)/jar $(MAPSFORGE_VENDOR)/elevate $(MAPSFORGE_VENDOR)/maps
	curl -fsSL -o $(MAPSFORGE_VENDOR)/jar/mapsforgesrv-fatjar.jar \
		https://github.com/telemaxx/mapsforgesrv/releases/download/$(MAPSFORGESRV_VERSION)/mapsforgesrv-fatjar.jar
	curl -fsSL -o $(MAPSFORGE_VENDOR)/elevate/Elevate.zip https://www.openandromaps.org/wp-content/users/tobias/Elevate.zip
	unzip -o -q $(MAPSFORGE_VENDOR)/elevate/Elevate.zip -d $(MAPSFORGE_VENDOR)/elevate
	cp "$(MAP_FILE)" $(MAPSFORGE_VENDOR)/maps/Cyprus_oam.map

mapsforge-up:
	docker run -d --rm --name $(MAPSFORGE_CONTAINER) -p 127.0.0.1:8486:8486 \
		-v "$(CURDIR)/tools/mapsforge":/srv:ro eclipse-temurin:21-jre \
		java -jar /srv/vendor/jar/mapsforgesrv-fatjar.jar -c /srv/config

mapsforge-down:
	docker stop $(MAPSFORGE_CONTAINER)

map-render:
	@test -n "$(NAME)" -a -n "$(BBOX)" || (echo "usage: make map-render NAME=x BBOX=south,west,north,east" && exit 1)
	$(PYTHON) tools/mapsforge/render_mbtiles.py --url "http://127.0.0.1:8486/{z}/{x}/{y}.png?task=$(TASK)" \
		--bbox "$(BBOX)" --pad-km $(PAD_KM) --zooms $(ZOOMS) $(ONE_BIT) --name "$(NAME)" maptile/$(NAME).mbtiles

ridden-roads:
	$(PYTHON) tools/build_ridden_layer.py rides/gpx/*.gpx --output rides/ridden_roads.npz

PI ?=
PI_DIR ?= pizero_bikecomputer
DEPLOY_FILES ?= $(wildcard maptile/*.mbtiles rides/ridden_roads.npz courses/*.tcx)

deploy:
	@test -n "$(PI)" || (echo "usage: make deploy PI=user@host [PI_DIR=pizero_bikecomputer]" && exit 1)
	rsync -av --relative $(DEPLOY_FILES) "$(PI):$(PI_DIR)/"

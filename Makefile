export UV_PROJECT_ENVIRONMENT := env
S2YT := env/bin/s2yt
PLAYLIST_ARG := $(if $(PLAYLIST),--playlist "$(PLAYLIST)",)

.DEFAULT_GOAL := help

.PHONY: help dev_install dev_run deploy step1 step2 step3 step4 step4_rebuild lint test

help:
	@echo "Spotify -> YouTube Music sync workflow:"
	@echo ""
	@echo "  make dev_install    Install dependencies into ./env using uv"
	@echo "  make step1          Save YouTube Music auth (browser.json) from clipboard"
	@echo "                      (Copy as cURL on a POST /browse request in music.youtube.com DevTools)"
	@echo "  make step2          Validate Exportify .csv files in playlists/ and preview top/bottom order"
	@echo "                      (Export from https://exportify.net and name file <Playlist Name>.csv)"
	@echo "  make step3          Dry-run sync: match tracks into cache/ytm_matches.json, show plan (no writes)"
	@echo "  make step4          Incremental sync: add missing tracks and reorder to match Spotify recency"
	@echo "  make step4_rebuild  Clean rebuild: clear existing YTM playlist and re-add all matched tracks in order"
	@echo ""
	@echo "Optional filter for step2/step3/step4/step4_rebuild:"
	@echo "  make step4 PLAYLIST='Roadtrip'"
	@echo ""
	@echo "Aliases and checks:"
	@echo "  make dev_run        Alias for step3 (dry-run)"
	@echo "  make deploy         Alias for step4 (incremental sync)"
	@echo "  make lint           Run ruff check and format check"
	@echo "  make test           Run pytest suite"

dev_install:
	uv sync

step1:
	$(S2YT) auth --clipboard

step2:
	$(S2YT) check $(PLAYLIST_ARG)

step3:
	$(S2YT) sync --dry-run $(PLAYLIST_ARG)

step4:
	$(S2YT) sync $(PLAYLIST_ARG)

step4_rebuild:
	$(S2YT) sync --rebuild $(PLAYLIST_ARG)

dev_run: step3

deploy: step4

lint:
	env/bin/ruff check src tests
	env/bin/ruff format --check src tests

test:
	env/bin/pytest

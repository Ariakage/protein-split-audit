# SPDX-License-Identifier: CC-BY-4.0

PANDOC ?= pandoc
PDF_ENGINE ?= typst
BUILD_DIR ?= build
MANUSCRIPT := paper.md
BIBLIOGRAPHY := paper.bib

.PHONY: all check clean

all: $(BUILD_DIR)/paper.html $(BUILD_DIR)/paper.pdf

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/paper.html: $(MANUSCRIPT) $(BIBLIOGRAPHY) | $(BUILD_DIR)
	$(PANDOC) $(MANUSCRIPT) --citeproc --standalone -o $@

$(BUILD_DIR)/paper.pdf: $(MANUSCRIPT) $(BIBLIOGRAPHY) | $(BUILD_DIR)
	$(PANDOC) $(MANUSCRIPT) --citeproc --standalone --pdf-engine=$(PDF_ENGINE) -o $@

check: all
	@test -s $(BUILD_DIR)/paper.html
	@test -s $(BUILD_DIR)/paper.pdf

clean:
	rm -rf $(BUILD_DIR)

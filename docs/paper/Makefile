# SPDX-License-Identifier: CC-BY-4.0

TYPST ?= typst
BUILD_DIR := build
TYPST_FLAGS := --root ../..

.PHONY: all clean check

all: $(BUILD_DIR)/paper.pdf

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/paper.pdf: paper.typ references.bib ../../results/released/v0.6.0/figures/macro_f1_by_split.pdf ../../results/released/v0.6.0/figures/generalization_gap.pdf | $(BUILD_DIR)
	$(TYPST) compile $(TYPST_FLAGS) paper.typ $@

check: all
	@test -s $(BUILD_DIR)/paper.pdf

clean:
	$(TYPST) compile --help >/dev/null
	find $(BUILD_DIR) -type f \( -name '*.pdf' -o -name '*.png' \) -delete 2>/dev/null || true

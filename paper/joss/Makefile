# SPDX-License-Identifier: CC-BY-4.0

.PHONY: all clean

all: build/paper.pdf

build/paper.pdf: paper.tex paper.bib figures/workflow.pdf
	mkdir -p build
	latexmk -pdf -outdir=build -interaction=nonstopmode -halt-on-error paper.tex

# pdflatex cannot include SVG directly; render the workflow diagram to PDF.
# The two result figures are referenced in place from the immutable v0.6.0
# release (../../results/released/v0.6.0/figures/) and are not copied.
figures/workflow.pdf: ../../docs/paper/images/workflow.svg
	mkdir -p figures
	mutool convert -F pdf -o $@ $<

clean:
	rm -rf build

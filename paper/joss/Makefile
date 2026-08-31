# SPDX-License-Identifier: CC-BY-4.0

.PHONY: all clean

all: build/paper.pdf

build/paper.pdf: paper.tex paper.bib
	mkdir -p build
	latexmk -pdf -outdir=build -interaction=nonstopmode -halt-on-error paper.tex

clean:
	rm -rf build

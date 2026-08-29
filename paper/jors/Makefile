# SPDX-License-Identifier: CC-BY-4.0

.PHONY: all clean

all: build/paper.docx

build/paper.docx: paper.md references.bib
	mkdir -p build
	pandoc paper.md \
	  --citeproc \
	  --bibliography references.bib \
	  --reference-links \
	  -o build/paper.docx

clean:
	rm -rf build

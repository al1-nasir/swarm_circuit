# Build the submission report

The final report is `output/pdf/swarmcircuit-hackathon-report.pdf`. It contains
six main pages, one reference page and two appendix pages. The abstract has 204
words. `report-qa.json` records the final hash and checks. The author approved submission and the terms; the official website displayed
“Project submitted” on November 9, 2026, at 14:56 Pakistan time. The confirmation
email has not been checked. The code repository remains private pending release.
The build process did not itself upload or submit anything.

From this directory, use XeLaTeX and BibTeX:

```bash
xelatex -interaction=nonstopmode -halt-on-error main.tex
bibtex main
xelatex -interaction=nonstopmode -halt-on-error main.tex
xelatex -interaction=nonstopmode -halt-on-error main.tex
```

Requires TeX Live packages providing `fontspec`, `setspace`, `microtype`,
`graphicx`, `booktabs`, `tabularx`, `amsmath`, `amssymb`, `tikz`, `natbib`,
`titlesec`, `enumitem`, `xurl`, `hyperref` and `fancyhdr`. The original build used
Arial and TeX Gyre Termes; the source falls back to Liberation Sans if Arial is
unavailable. Fonts are embedded in the delivered PDF. No external figure files,
shell escape, network access, API credentials or model calls are needed to build.

`author.tex` contains the confirmed author name and the stated independent
affiliation. The bibliography contains primary research, official documentation
and human-rights/risk-management sources. `abstract.txt` mirrors the submission
abstract without LaTeX markup.

The layout adapts the current [official Apart Research template](https://docs.google.com/document/d/1_1_27EyZriMlc8n8EBE2YScaeyMjm-8xjR097nmHXAE/copy?usp=sharing):
US Letter, one-inch margins, Arial 11-point body text, 1.15 line spacing and the
recommended section structure. The unavailable Old Standard TT title font is
replaced by TeX Gyre Termes. The required Limitations and Dual-Use / Ethical
Considerations appendix and LLM Usage Statement are included.

Before replacing the delivered PDF after an edit, rebuild, render every page with
`pdftoppm`, inspect all pages, check for unresolved citations/overfull boxes and
update the QA hash. Do not overwrite the historical November 5 preparation draft.

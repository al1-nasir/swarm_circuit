# SwarmCircuit submission materials

Prepared locally for **SwarmCircuit: Checking Agent Handoffs Against Source State**.
Author: Muhammad Ali Nasir. Report affiliation: Independent researcher, Islamabad,
Pakistan. The author reviewed and approved the final submission.

- `report/swarmcircuit-hackathon-report.pdf`: final reviewed PDF report.
- `report/main.tex`, `author.tex`, `references.bib`, `abstract.txt`: editable report
  sources. `main.bbl`, when present, is the generated bibliography.
- `source/swarmcircuit-source-2026-11-09.zip` and its manifest: source, contracts,
  migrations, tests, static assets and the retained actual live-handoff evidence.
- `demo-script.md`: a four-minute demonstration using the retained live case.
- `SUBMISSION_MANIFEST.json`: SHA-256 values for the included files.

The separate local `submission-details.md` and `.json` contain a contact email for
form preparation. They are deliberately excluded from this shareable bundle.

## Rebuild the report

Use XeLaTeX and BibTeX with a TeX Live distribution. From the report directory:

```bash
xelatex -interaction=nonstopmode -halt-on-error main.tex
bibtex main
xelatex -interaction=nonstopmode -halt-on-error main.tex
xelatex -interaction=nonstopmode -halt-on-error main.tex
```

The report uses Arial for its body and TeX Gyre Termes for its title. The source
falls back to Liberation Sans if Arial is absent; font binaries are not included. Required packages include
fontspec, setspace, microtype, tikz, natbib, titlesec, enumitem, xurl, hyperref and
fancyhdr. The source notes its adaptation of the official template: US Letter,
one-inch margins, 11-point Arial and 1.15 line spacing.

## Submission and access

The known code destination is https://github.com/al1-nasir/swarm_circuit. It is
private during preparation. The author will push and make it accessible later;
this archive does not establish that judges can currently access that URL.

The official deadline is **November 9, 2026, at 11:59 UTC / 16:59 Pakistan time**.
The final PDF was submitted through the official event form. The official
website displayed “Project submitted” on **November 9 at 14:56 Pakistan time**,
after the author approved submission and the terms. The confirmation email has
not been checked. This local ZIP has not itself been uploaded or published;
the code repository remains private pending the author’s planned release.

[Official event and submission form](https://apartresearch.com/sprints/swarm-alignment-2026).

## Evidence boundaries

The actual retained case completed 6/6 SDK tasks using two roles on the same
configured provider and two calls. The provider reported 997 input and 304 output
tokens. No repair was needed; typed-claim checks passed. Controlled failure tests
are implementation evidence, not additional real-model samples. The older
synthetic study and failed pilots remain historical preparation. No general
safety guarantee, error-rate estimate, cost saving or hackathon placement is claimed.

The three completed backend, frontend and gateway release-check logs are
included as test evidence. No `.env`, private database, backups, dependency
installation, build cache or application runtime log is included. The repository has no selected open-source license;
this local archive does not confer redistribution rights. Follow the source
bundle's README to install and run the application.

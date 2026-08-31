# PaperLyft WeasyPrint Fork

This repository is the PaperLyft-owned WeasyPrint fork.

## Repository safety

- The only writable GitHub repository is:
  `https://github.com/vctrx-dev/WeasyPrint.git`
- `origin` must always fetch and push to `vctrx-dev/WeasyPrint`.
- `Kozea/WeasyPrint` is read-only upstream reference material.
- Never push, open a pull request, create a release, create a tag, or modify anything in `Kozea/WeasyPrint`.
- Never force-push or rewrite `main`.
- Work on `codex/*` feature branches.
- Before every push, verify the push remote is `origin`.
- Push only after all required tests pass.

Configure upstream as fetch-only:

git remote add upstream https://github.com/Kozea/WeasyPrint.git
git remote set-url --push upstream DISABLED

## Product boundary

PaperLyft converts scanned pages into semantic HTML and renders them as tagged PDF/UA-1 documents.

WeasyPrint owns standards-correct HTML/CSS-to-PDF behavior. It must not contain:

- OCR or AI behavior
- source-document interpretation
- PaperLyft workflow logic
- LLM repair logic
- visual comparison against scanned pages
- changes that falsify HTML semantics to satisfy veraPDF

Prefer standards-correct fixes useful to all WeasyPrint users. Add PaperLyft-specific APIs only when a verified requirement cannot be expressed through existing WeasyPrint behavior.

## Development

Use behavior-first TDD:

1. Add one focused regression test.
2. Run it and confirm it fails for the expected reason.
3. Make the smallest implementation change.
4. Run the focused test.
5. Run related existing tests.
6. Run the complete pytest suite and Ruff.
7. Validate emitted PDF independently where PDF structure matters.

Do not redesign the tagging architecture unless focused failing tests prove a local correction is insufficient. Stop and present evidence before beginning such a redesign.

Preserve existing upstream behavior and keep future upstream merges practical.

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

## Docker, disk & cache hygiene (mandatory, every session)

Disk and RAM on this machine are scarce. Docker Desktop's disk once grew to 76 GB from leftover images, stopped containers, anonymous volumes and 30 GB of build cache. Leave Docker and caches cleaner than you found them.

### Check every time
- Before any Docker work, and again before you finish the task, run `docker ps -a`, `docker images`, `docker volume ls`, `docker system df`.
- If Docker is running, do this check at the end of every task, even when the task did not touch Docker.
- Remove leftovers (rules below), then tell the user what you removed and how much space it freed.

### Shared engine: keep list
One Docker engine serves all projects (paperlyft, WeasyPrint, gtncc, others). Never delete another project's items. Never delete these without the user's explicit permission:

| Kind | Keep |
|---|---|
| Images | newest `plyft-local-quality:<tag>` only, `plyft-weasyprint:latest`, `plyft-pipeline-worker-base:latest`, `node:22-bookworm-slim`, `amazon/dynamodb-local` (untagged, pinned by digest `ff89bd48ff32…`), `verapdf/cli:v1.30.2`, `postgres:16-alpine` |
| Data volumes | `paperlyft_plyft-postgres-data`, `paperlyft_plyft-minio-data`, `gtncc-pgdata`, `gtncc-quote-local-v1`, `vctrx_vctrx_pgdata`, `vscode` |

Any other named volume: ask the user before deleting. It may hold data.

### Containers
- Always `docker run --rm` with a project-prefixed `--name`.
- Set limits on every run: `--memory` and `--cpus` (default `--memory 2g --cpus 2`; raise only when the task needs it).
- Stop and remove every container you start before finishing, including after failures, timeouts and interrupted runs. Use `docker compose down` when done (no `-v`).
- Never leave databases, dev servers or workers running after the task. No exited containers may remain.

### Images
- One tag per image name. After building a new tag, delete the older tags of that repository.
- Do not pull images the project does not use. Reuse images already on the keep list; prefer `-slim`/`-alpine`.
- Delete local copies of images already pushed to a registry (ECR / CDK asset images) after the push or deploy.

### Build cache
- After every build, cap it: `docker builder prune -f --max-used-space 5gb`.
- If `docker system df` shows build cache above 5 GB, prune it.

### Volumes
- Never create anonymous volumes. Use named, project-prefixed volumes.
- Throwaway volumes (node_modules, package caches, test scratch) are deleted when the task ends.
- Never run `docker compose down -v` on a stack with a data volume from the keep list.

### Forbidden without asking the user
`docker system prune -a`, `docker system prune --volumes`, `docker image prune -a`, `docker volume prune -a`. They delete keep-list items (untagged digest-pinned images, data volumes). Remove things by name instead.

### Safe cleanup (run at the end of Docker work)
```powershell
docker container prune -f
docker image prune -f
docker builder prune -f --max-used-space 5gb
docker volume ls -qf dangling=true | Where-Object { $_ -match '^[0-9a-f]{64}$' } | ForEach-Object { docker volume rm $_ }
docker system df
```

### Caches, temp files & memory
- Reuse the existing install (node_modules, venv, lockfile). Do not create extra caches, venvs or node_modules copies.
- Never copy the whole repo for an experiment. Use `git worktree add` and `git worktree remove` when finished.
- Delete temp dirs and outputs you created (`%TEMP%\<project>-*`, scratch dirs, extracted archives, rendered test files) before finishing.
- If disk is low, package caches are safe to clear: `uv cache clean`, `pnpm store prune`, `npm cache clean --force`.
- Run one heavy job at a time (Docker build, full test suite, headless browser). Kill background processes and browsers you started.
- Pruning does not shrink `%LOCALAPPDATA%\Docker\wsl\data\ext4.vhdx`. If that file is more than 10 GB larger than the `docker system df` total, tell the user it needs compacting.

### WeasyPrint specifics
- This fork is exercised through PaperLyft's `plyft-weasyprint:latest` image. Rebuild that one tag in place; don't create extra WeasyPrint image tags.
- Use the existing virtualenv. Do not create per-task venvs.
- Write rendered test PDFs and HTML to a temp dir and delete it after verification. Don't commit or leave them in the repo.

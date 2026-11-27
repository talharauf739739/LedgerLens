# LedgerLens

Open-source (MIT) document intelligence for fintech: messy financial PDFs and scans in, grounded and validated JSON out. Every extracted value must point back to its source on the page. Full spec: [spec.md](spec.md).

**Status:** Phase 2 in progress. Exists: `config.py`, `llm/provider.py`, `storage/`, `db/` (+ `migrations/`), `cache.py`, `api/main.py` (health only), `cli.py`, `schemas/` and `rules/` (bank_statement, invoice), `synth/` (generators with exact ground truth), `normalize.py`, `pipeline/` (text layer + RapidOCR spans, deskew, table Markdown), `agents/` (drafts, versioned prompts, baseline extractor), `pipeline/ground.py` (receipts for every value; unfound values nulled) and `pipeline/process.py` (parse -> extract -> ground -> validate), and `eval/` (parse recall; raw vs grounded extraction, hallucination rate). Real-LLM numbers come from `notebooks/kaggle_eval.ipynb`. `agents/workflow.py` is the Agent Framework graph (parse -> classify -> extract -> ground -> validate, one grounding-driven retry; every step traced) and `ui/` is the Streamlit demo and review screen (`demo.py` scenarios, proofs and stats, `components.py` HTML cards, `review.py` page rendering; receipts drawn on the page, corrections, approve/reject; uploads of PDFs or images, read with OCR or fully extracted). Next: API routes, worker and PostgreSQL audit log (phase 3 wiring), then the eval on Kaggle. The rest of the layout below is the target.

## Non-negotiable rules

1. **No secrets in git.** Only `.env.example` is committed. `.env` is git-ignored and gitleaks runs as a pre-commit hook. Runtime secrets come from Key Vault (Floci locally, Azure in the cloud) via `azure-keyvault-secrets`; in the cloud use `DefaultAzureCredential` / managed identity.
2. **Synthetic or public data only.** Never use real personal financial documents, real names, account numbers, SSNs or IDs. Generate them with Faker and test IBAN generators. Datasets live in `data/` (git-ignored) and are fetched by `scripts/download_data.py`; record each dataset's license in `data/LICENSES.md`.
3. **MIT-compatible dependencies only.** No GPL/AGPL in the core: not PyMuPDF, Marker or Surya. Use pypdfium2 and pdfplumber instead. Check the license of every new dependency (`pip-licenses`).
4. **Money is `Decimal`, never `float`.** Serialize it as a decimal string. Compare with a tolerance of `Decimal("0.01")`.
5. **Grounding or nothing.** Every non-null value needs a source span (page + bbox) that matches the OCR text. Ungrounded values become `null` with `status="ungrounded"` and go to the review queue. Never guess.
6. **Agents propose; code decides.** The LLM fills schemas from what is printed. Deterministic Python rules do the math and decide acceptance. Agents never compute values that aren't printed.
7. **Document text is untrusted.** Prompts must forbid following instructions found inside documents, and output that doesn't match the JSON schema is rejected.
8. **Mask PII** (Presidio) before anything is logged or sent to a cloud LLM. Store account numbers masked (`****1234`).
9. **Free and open source by default.** Everything needed to build, run and demo the project must be free and open source (spec §10a). A paid service may only be an optional swap-in for a free one. Use Valkey, not Redis 8 (its license includes AGPL/SSPL). Python is the only application language: no Java or Node services.

## Infrastructure roles (don't blur them)

- **PostgreSQL** is the system of record: jobs, results (JSONB), audit log, review queue, API-key hashes. Schema changes go through Alembic migrations.
- **Valkey/Redis** is a cache only: OCR/LLM results keyed by page hash, rate-limit counters, job progress pub/sub. Code must work if it's flushed, so never store anything there you can't recompute.
- **Azure Queue** (Floci locally) carries extraction jobs. **Blob** holds raw documents, page images and result files. **Key Vault** holds secrets.
- **Nginx** fronts the API and UI on the VM (TLS, 20 MB upload limit).

## Stack

Python 3.12 with `uv` · FastAPI + Pydantic v2 · Streamlit · Microsoft Agent Framework · pdfplumber + pypdfium2 (text layer), RapidOCR on ONNX Runtime (scans) · rapidfuzz · PostgreSQL 17 (SQLAlchemy 2 + asyncpg + Alembic) · Valkey 8 (redis-py) · Floci-az (local Azure emulation in Docker) · Nginx · Presidio · OpenTelemetry · pytest + hypothesis · ruff, mypy, pre-commit

LLM access goes only through `ledgerlens/llm/provider.py` (`LLM_PROVIDER = foundry_local | ollama | azure_foundry`, all OpenAI-compatible). Don't hard-code the Foundry Local port; discover it with `foundry-local-sdk`. Verify model IDs against each catalog, since they change.

## Layout

```
ledgerlens/
  api/        FastAPI routers (/v1/documents, /v1/extract, /v1/jobs/{id})
  worker/     queue consumer
  pipeline/   preprocess, parse, ocr, ground
  agents/     classifier, extractor, validator, reconciler (+ prompts/, versioned)
  schemas/    Pydantic model per doc type, registered in __init__.py::REGISTRY
  rules/      deterministic validators, pure functions
  llm/        provider abstraction
  storage/    blob/queue/table/keyvault wrappers
  security/   PII masking, auth
ui/           Streamlit app
synth/        synthetic document generator + ground truth
eval/         metrics, runners, reports
infra/        Bicep for Azure
tests/        unit, rules (hypothesis), golden snapshots
```

## Commands

- `uv sync`: install dependencies
- `uv run pytest`: unit tests (integration tests are excluded by default; `-m integration` runs them against the compose stack)
- `uv run ruff check . && uv run ruff format --check . && uv run mypy ledgerlens synth eval ui`: lint, format and type-check (mypy is strict). CI runs all of these plus a license gate and gitleaks.
- `uv run ledgerlens hello`: send one prompt through the configured LLM provider
- `uv run ledgerlens init-storage`: create the blob container and jobs queue
- `uv run ledgerlens read <file>`: text layer or OCR of a PDF or image, printed as Markdown (no LLM)
- `uv run ledgerlens extract <file> [--doc-type auto|bank_statement|invoice] [-o out.json]`: full workflow on one PDF or image (needs an LLM provider). `pipeline/ingest.py` turns images into image-only PDF pages, so they take the OCR path.
- `uv sync --extra ui && uv run streamlit run ui/streamlit_app.py`: review UI. Replay mode works offline (synthetic truth stands in for the LLM). Uploads (PDF or images; read-only OCR, or full extraction with an LLM) only with `LEDGERLENS_ALLOW_UPLOAD=1`, and only where viewers are restricted (a private Streamlit app, a laptop). A public deployment must stay synthetic-only. Community Cloud deps are in `ui/requirements.txt`. Keep `ui/requirements.txt` pinned to `uv.lock` when bumping app deps.
- `uv run python -m synth --count 20`: synthetic PDFs + `.truth.json` into `data/synth/` (clean, noisy, tampered)
- `docker compose up`: Floci, PostgreSQL, Valkey, Jaeger, API, worker and UI
- `uv run alembic upgrade head`: apply database migrations
- `uv run python -m eval parse`: parser recall vs synthetic truth (no LLM); `python -m eval extract --limit 5`: baseline LLM extraction. Reports go to `reports/`.

## Machine limits (developer laptop)

- The dev laptop has 8 GB RAM, an integrated GPU and a 4-core CPU. Keep the local stack light: no PyTorch, Docling or local 4B+ LLMs installed by default. Ask before adding any heavy dependency.
- Heavy jobs (LLM extraction evals, Docling comparison) run on free cloud notebooks (Kaggle GPU) using the same code and the Ollama provider: `notebooks/kaggle_eval.ipynb`. Docker only when needed, then `docker compose stop`.

## Ground-truth conventions

- `bbox` is `[x0, y0, x1, y1]` in PDF points, **top-left origin**, `page` 1-based. Scans use the same space.
- Truth files hold the stored form (identifiers masked); `synthetic.printed` holds the raw printed text per field for grounding tests.
- `tests/test_synth.py` is the contract: clean docs pass every rule, tampered docs fail exactly `expected_failures`, and the PDF text inside every truth bbox equals what was printed. Keep it green when touching a generator.

## Working conventions

- To add or change a document type, use the `fintech-doc-extraction` skill (`.claude/skills/fintech-doc-extraction/SKILL.md`).
- Write a failing test before fixing an extraction or rule bug.
- Bump the prompt version (`v1.md` → `v2.md`) instead of editing a prompt in place.

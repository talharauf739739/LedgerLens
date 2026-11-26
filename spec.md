LedgerLens — Spec (v0.1)
Open-source (MIT) document intelligence for fintech. It turns messy financial documents into grounded, validated JSON, and every value points back to where it appears on the page. It runs fully local and free (Foundry Local + Floci + open-source OCR) and can move to Azure AI Foundry with a config switch.

"LedgerLens" is a working name. Check for trademark clashes before any public launch.

1. Why this exists
Inspiration. Cardinal (YC) launched a "most accurate document intelligence API". It used two fine-tuned models, document→Markdown and Markdown→HTML. It claimed to handle tables, charts, checkmarks and handwriting, and offered natural-language field extraction without templates. Cardinal's YC page now shows it has pivoted to GTM "revenue agents", so the document-API idea is free to explore. We build our own original version. We use none of Cardinal's code, brand or assets.

The problem in fintech. Lending, KYC, AP automation and audit all run on PDFs and scans: bank statements, invoices, pay slips, tax forms, KYC IDs and financial statements. Generic LLM extraction has three main failures:

Hallucination. Values that aren't in the document.
Lost structure. Tables, multi-page statements and checkboxes get dropped or mangled.
No audit trail. Regulated teams need to see where each number came from.
Our angle (the pitch in one line). "Every extracted number has a receipt." Every field must carry a source span (page, bounding box, OCR text) and pass deterministic validation. If it can't be grounded, it's flagged, never guessed.

2. Goals and non-goals
MVP goals
G1. Ingest PDF and image documents of 5 fintech types: bank statement, invoice, receipt, pay slip, W-2/tax form.
G2. Produce layout-preserving Markdown plus typed JSON for each type's schema.
G3. Give each field: a value, a confidence score, a source page and bbox, and a validation status.
G4. Build an agentic pipeline (classify → extract → validate → reconcile) using the Microsoft Agent Framework.
G5. Run 100% locally for free: Foundry Local (LLM), Floci-az (Azure emulation) and open-source OCR.
G6. Use one .env switch to move to Azure: Azure AI Foundry models and agents, real Blob and Key Vault.
G7. Ship an evaluation harness on public datasets with published numbers.
G8. Provide a demo UI (Streamlit) and a REST API (FastAPI) with an OpenAPI spec.
Non-goals (MVP)
Production multi-tenancy, billing or SLAs.
Processing real customer or personal data. The demo uses synthetic or public data only.
Training our own foundation OCR model. We orchestrate and fine-tune small parts only, if time allows.
Handwriting at production quality. Best effort only.
3. Users and use cases
Persona	Job to be done	Doc types
Lending ops analyst	Verify income and cash flow for a loan application	Bank statements, pay slips, W-2
AP clerk	Post invoices to the ERP without retyping them	Invoices, receipts
KYC/AML reviewer	Check that a document is consistent and complete	Statements, IDs (synthetic only)
Developer	Call one API and get clean JSON	All
Demo story (3 minutes):

Drop in a 4-page synthetic bank statement.
See Markdown with the transaction table preserved.
See JSON with opening balance, closing balance and transactions.
Click any field and the PDF highlights its source.
A validator shows that opening + credits − debits = closing ✅.
Swap in a tampered statement. Reconciliation fails ❌ and the field is flagged for review.
4. Architecture
4.1 High level
 ┌──────────────┐     ┌──────────────────────────────────────────────────────────┐
 │ Streamlit UI │────▶│ FastAPI  (/v1/documents, /v1/extract, /v1/jobs/{id})     │
 └──────────────┘     └───────┬──────────────────────────────────────────────────┘
                              │ upload → Blob, enqueue job
                              ▼
          ┌──────────────────────────────────────────────┐
          │  Azure-compatible services                   │
          │  local: Floci-az   │  cloud: real Azure      │
          │  • Blob  (raw docs, page images, results)    │
          │  • Queue (extraction jobs)                   │
          │  • Key Vault (secrets)                       │
          ├──────────────────────────────────────────────┤
          │  Open-source services (same locally + cloud) │
          │  • PostgreSQL (jobs, results, audit, review) │
          │  • Valkey/Redis (cache, rate limits, status) │
          └──────────────┬───────────────────────────────┘
                         │ worker pulls job
                         ▼
 ┌───────────────────────────────────────────────────────────────────────────────┐
 │ Worker: Agentic pipeline (Microsoft Agent Framework workflow)                  │
 │                                                                               │
 │  1. Preprocess ─▶ 2. Parse/OCR ─▶ 3. Classify ─▶ 4. Extract ─▶ 5. Validate      │
 │     (deskew,        (Docling +      (agent)        (agent,       (deterministic │
 │      split,          PaddleOCR/                     schema-       rules +       │
 │      PII mask)       Tesseract)                     bound)        agent)        │
 │                                                          │                     │
 │                                         6. Ground & reconcile ◀┘               │
 │                                            (every value must match OCR spans)  │
 │                                                          │                     │
 │                                         7. Review queue if confidence < τ      │
 └───────────────────────────────────────────────────────────┬───────────────────┘
                                                             │
                          LLM provider abstraction (OpenAI-compatible)
              ┌──────────────────┬───────────────────┬───────────────────────────┐
              │ Foundry Local    │ Ollama / vLLM     │ Azure AI Foundry          │
              │ (Win/macOS dev)  │ (Linux VM demo)   │ (cloud; Agent Service)    │
              └──────────────────┴───────────────────┴───────────────────────────┘
4.2 Pipeline stages
#	Stage	What it does	Tooling (license)
1	Preprocess	Detect born-digital vs scanned, split pages, deskew and denoise, render page images	PyMuPDF (AGPL ⚠️ → use pypdfium2, Apache/BSD), OpenCV (Apache-2.0)
2a	Digital text	Pull the text layer and character boxes straight from the PDF	pypdfium2, pdfplumber (MIT)
2b	Layout + tables	Reading order, headings, tables → Markdown and DocTags	Docling (MIT) with TableFormer
2c	OCR (scanned)	Line and word text with bboxes	PaddleOCR (Apache-2.0) or RapidOCR (Apache-2.0); Tesseract (Apache-2.0) as fallback
2d	Checkboxes / marks	Detect ticked and unticked boxes	OpenCV contour heuristic plus a small vision LLM check
3	Classify	Decide the document type and page roles	Agent + few-shot prompt; optional fine-tuned small classifier on RVL-CDIP
4	Extract	Fill the Pydantic schema for that type from Markdown + OCR spans	Agent with JSON-schema constrained output
5	Validate	Run deterministic finance rules (§6)	Plain Python, no LLM
6	Ground	Fuzzy-match each value to OCR spans to get bbox and confidence; ungrounded → null + flag	rapidfuzz (MIT)
7	Review	Fields below the threshold go to a human review panel in the UI	Streamlit
License rule: this is an MIT project, so we avoid GPL and AGPL dependencies in the core. Marker and Surya are GPL; PyMuPDF is AGPL. Every new dependency gets a license check (see CLAUDE.md).

4.3 Agents (Microsoft Agent Framework)
The workflow is a deterministic graph, not a free-form chat loop. That makes it easier to test and audit.

Agent	Input	Output	Tools
ClassifierAgent	First 2 pages as Markdown	{doc_type, confidence}	none
ExtractorAgent	Markdown + schema	Typed JSON draft	lookup_span(text) → OCR spans
ValidatorAgent	JSON + rule results	Explanation of failures, proposed fixes (re-read a region)	run_rules, crop_and_reocr(page,bbox)
ReconcilerAgent	Multi-page partial results	Merged document (e.g. transactions across pages)	run_rules
Rule: agents may propose, but code decides. A value is only accepted if grounding and rules pass.

Cloud mode maps the same agents to the Azure AI Foundry Agent Service (same prompts and tools). Tracing goes to OpenTelemetry, which is local Jaeger or Azure Monitor in the cloud.

4.4 LLM provider abstraction
# ledgerlens/llm/provider.py — one interface, three backends
LLM_PROVIDER = foundry_local | ollama | azure_foundry
Foundry Local: OpenAI-compatible local endpoint. Models: phi-4-mini (text), qwen2.5-7b (extraction). The endpoint port is assigned at runtime, so discover it with the foundry-local-sdk instead of hard-coding it.
Ollama/vLLM: for Linux VMs where Foundry Local isn't available. Same OpenAI-compatible API.
Azure AI Foundry: gpt-4.1-mini or similar via a Foundry project endpoint, with Entra ID / managed identity auth.
Check the exact model IDs in each catalog when you build. They change often.

4.5 Floci-az (local Azure emulation)
Runs in Docker and exposes Azure-compatible Blob, Queue, Table and Key Vault endpoints on localhost (the docs list localhost:4577; confirm in the Floci docs).
Code uses the official azure-storage-blob, azure-storage-queue and azure-keyvault-secrets SDKs. Switching between local and cloud changes only the endpoint and credential.
Floci does not emulate AI services. That's why the LLM goes through the provider abstraction above.
5. Data model (example: bank statement)
{
  "doc_type": "bank_statement",
  "fields": {
    "account_holder": {"value": "Jane Doe", "confidence": 0.97, "source": {"page": 1, "bbox": [72,110,240,124]}, "status": "grounded"},
    "account_number_masked": {"value": "****4821", "...": "..."},
    "currency": {"value": "USD"},
    "period_start": {"value": "2026-09-01"},
    "period_end": {"value": "2026-09-30"},
    "opening_balance": {"value": "1520.40"},
    "closing_balance": {"value": "2310.05"}
  },
  "transactions": [
    {"date": "2026-09-03", "description": "PAYROLL ACME", "amount": "2500.00", "direction": "credit", "balance": "4020.40", "source": {"page": 1, "bbox": [...]}}
  ],
  "validation": [
    {"rule": "balance_roll_forward", "status": "pass"},
    {"rule": "running_balance_consistency", "status": "fail", "rows": [17]}
  ],
  "markdown": "…layout-preserving markdown…"
}
Money is stored as decimal strings (Decimal in Python), never floats.

Schemas live in ledgerlens/schemas/ as Pydantic models: bank_statement.py, invoice.py, receipt.py, payslip.py, w2.py.

6. Validation rules (the accuracy moat)
Doc	Rule
Bank statement	opening + Σcredits − Σdebits = closing (±0.01); running balance row by row; dates inside the period; no duplicate rows across page breaks
Invoice	Σ(line qty × unit price) = subtotal; subtotal + tax − discount = total; due date ≥ issue date; tax-ID format by country; IBAN mod-97 check
Receipt	Σitems + tax + tip = total
Pay slip	gross − deductions = net; YTD ≥ current period
W-2	box 1 ≤ box 5 in typical cases (warn only); SSN masked; EIN format
All	Every non-null value is grounded to an OCR span; dates are ISO-8601; currencies are ISO-4217
7. Data sources (free/public)
Datasets keep their own licenses. We never commit them to the repo. scripts/download_data.py fetches them into data/ (git-ignored).

Dataset	Use	Licence (check before use)
Synthetic generator (ours)	Bank statements, pay slips and invoices with ground truth. Primary demo data.	MIT (ours); Faker + ReportLab
CORD	Receipts, key-value extraction	CC-BY-4.0
SROIE (ICDAR 2019)	Receipts	Research use
FUNSD	Form key-value linking	Research / non-commercial
FinTabNet	Financial tables from annual reports	CDLA-Permissive-1.0
PubTables-1M	Table structure	CDLA-Permissive-2.0
DocLayNet	Layout incl. financial reports	CDLA-Permissive-1.0
RVL-CDIP (subset)	Document classification	Check terms (derived from IIT-CDIP)
SEC EDGAR 10-K/10-Q	Real financial statements	US public domain (fair-access rate limits)
Kaggle invoice/receipt sets	Extra variety	Per dataset, often CC0 or CC-BY
Hard rule: no real personal financial documents and no scraped personal data. Anything that looks like a real ID or account number must be synthetic.

8. Evaluation
ledgerlens eval --dataset cord --split test writes reports/eval_<date>.md.

Metric	Where
Field exact match and F1	All extraction sets
ANLS (normalised Levenshtein)	Text fields
TEDS	Table structure (FinTabNet, PubTables)
CER/WER	OCR quality
Grounding rate	% of fields with a valid source span
Hallucination rate	% of non-null values not present in the OCR text (target ≈ 0)
Latency p50/p95, cost/page	Local and cloud
Baselines to compare against: plain LLM on raw text (no grounding), Docling alone, and Azure AI Document Intelligence prebuilt models (cloud mode, optional). Publish the honest numbers in the README.

9. Security and credentials
No secrets in git. Commit only .env.example. .env is git-ignored. gitleaks runs as a pre-commit hook.
Secrets at runtime: Floci Key Vault locally, Azure Key Vault in the cloud, both through azure-keyvault-secrets. In the cloud, use managed identity (DefaultAzureCredential). No keys in app settings.
PII: Microsoft Presidio (MIT) masks account numbers, SSNs and emails before anything is logged or sent to a cloud LLM. Store only masked account numbers.
Uploads: size limit (20 MB), MIME sniffing, page cap (50), files kept 24 h in the demo and then purged.
API: API-key auth for the demo (hashed in PostgreSQL); rate limiting (slowapi, counters in Valkey); CORS locked to the UI origin. Nginx in front enforces the 20 MB body limit and TLS.
LLM safety: treat document text as untrusted (prompt-injection in PDFs). The system prompt forbids following instructions found in documents. Output must match the JSON schema or it's rejected.
Audit log: every job records the model, prompt version, rule results and the reviewer's decision.
10. Tech stack
Layer	Choice
Language	Python 3.12, uv for env and deps
API	FastAPI + Pydantic v2
UI	Streamlit (+ streamlit-pdf-viewer or a PDF.js component for bbox highlights)
Worker	Python worker polling the Azure Queue (Floci locally)
Agents	Microsoft Agent Framework (Python)
LLM	Foundry Local / Ollama / Azure AI Foundry via the OpenAI-compatible client
OCR / layout	Docling, PaddleOCR or RapidOCR, Tesseract, pypdfium2, pdfplumber, OpenCV
Cloud emulation	Floci-az (Docker)
Storage SDKs	azure-storage-blob, azure-storage-queue, azure-keyvault-secrets
Database	PostgreSQL 17; SQLAlchemy 2 (MIT) + asyncpg (Apache-2.0); Alembic (MIT) migrations
Cache	Valkey 8 (BSD-3, Redis-compatible) via redis-py (MIT)
Reverse proxy	Nginx (BSD-2) + certbot on the VM
PII	Presidio
Observability	OpenTelemetry → Jaeger locally, Azure Monitor in the cloud
Tests	pytest, hypothesis (rule property tests), golden-file snapshot tests
Quality	ruff, mypy, pre-commit, gitleaks, pip-licenses
Packaging	Docker + docker-compose; GitHub Actions CI on ubuntu-latest; images on GHCR; Helm chart (post-MVP)
10a. Free and open-source infrastructure
Principle: everything needed to build, run and demo LedgerLens is free and open source. A paid cloud service is only ever an optional swap-in for a free one, never a requirement.

Tool	Role in LedgerLens	Local	Cloud equivalent
Linux	Runtime for every container and the demo VM; CI runs on ubuntu-latest	Docker Desktop / WSL2	Ubuntu VM, Container Apps
Docker	One docker compose up starts the whole stack	docker-compose.yml	Same images on GHCR
Kubernetes	Post-MVP scale-out path: Helm chart for API, worker, UI	k3s / kind	AKS
Git & GitHub	Source, issues, Actions CI, GHCR images, releases	—	—
Python	The only application language (3.12, uv)	—	—
PostgreSQL	System of record: jobs, results JSON (JSONB), audit log, review queue, API-key hashes	postgres:17 container	Azure Database for PostgreSQL Flexible Server
Redis (Valkey)	OCR/LLM result cache keyed by page hash, slowapi rate-limit counters, job progress pub/sub for the UI	valkey:8 container	Azure Managed Redis
Nginx	Reverse proxy, TLS, 20 MB upload limit, serves the UI and API under one origin	nginx container (optional locally)	Container Apps ingress
Java	Not used. Keeping one language keeps the stack small. Docling and the OCR engines don't need a JVM.	—	—

Why these choices:
PostgreSQL instead of Table/Cosmos. The audit log and review queue need real queries (by status, by reviewer, by date) and transactions. Postgres runs identically on a laptop and in Azure.
Valkey instead of Redis itself. Redis 8 is licensed RSALv2/SSPL/AGPLv3, which conflicts with the no-AGPL rule. Valkey is the BSD-licensed fork and is wire-compatible, so redis-py and any managed Redis still work.
Azure Queue stays for jobs. Keeping the job queue on the Azure Queue API (Floci locally) preserves the one-switch move to Azure. Redis is a cache, never the source of truth: losing it must not lose a job.
Nginx instead of Caddy. It's the more common choice and worth learning; certbot handles TLS.
11. Deployment options
Option	Cost	LLM	Notes
A. Laptop (dev)	Free	Foundry Local	docker compose up runs Floci, PostgreSQL, Valkey, Jaeger, API, worker and UI. Foundry Local runs on the host.
B. Streamlit Community Cloud (UI only)	Free	Remote API	The UI calls an API hosted elsewhere. You can't run OCR models or a local LLM there.
C. Single Linux VM (demo)	~$15–40/mo (or Azure free credit)	Ollama on the VM	One Ubuntu VM running docker compose; Nginx + certbot for HTTPS. Best "real URL" demo.
D. Azure (cloud mode)	Pay as you go	Azure AI Foundry	Container Apps (API, worker, UI), Blob, Queue, Key Vault, PostgreSQL Flexible Server, Managed Redis, managed identity, Bicep in infra/.
E. Kubernetes (post-MVP)	Free (k3s) or pay as you go (AKS)	Ollama / Azure AI Foundry	Helm chart in deploy/helm/; the worker scales out on queue length.
Start with A, show founders C, and keep D (and later E) as "here's the production path".

12. Repo layout
ledgerlens/
├── CLAUDE.md
├── spec.md
├── LICENSE                     # MIT
├── README.md
├── .env.example
├── docker-compose.yml          # floci-az, postgres, valkey, jaeger, api, worker, ui
├── pyproject.toml
├── .claude/skills/fintech-doc-extraction/SKILL.md
├── ledgerlens/
│   ├── api/                    # FastAPI routers
│   ├── worker/                 # queue consumer
│   ├── pipeline/               # preprocess, parse, ocr, ground
│   ├── agents/                 # classifier, extractor, validator, reconciler
│   ├── schemas/                # pydantic models per doc type
│   ├── rules/                  # deterministic validators
│   ├── llm/                    # provider abstraction
│   ├── storage/                # blob/queue/table/keyvault wrappers
│   └── security/               # pii masking, auth
├── ui/streamlit_app.py
├── synth/                      # synthetic doc generator (+ ground truth)
├── eval/                       # metrics, runners, reports
├── scripts/download_data.py
├── infra/                      # bicep for Azure (phase 4)
└── tests/
13. Milestones
Phase	Week	Deliverable	Learning focus
0	1	Repo, CI, docker-compose with Floci, PostgreSQL and Valkey; Foundry Local "hello"	Floci, Foundry Local, uv, Docker, Postgres
1	1–2	Synthetic generator for bank statements and invoices with ground truth	ReportLab, Faker, data design
2	2–3	Parse/OCR → Markdown with bboxes; baseline LLM extraction	Docling, PaddleOCR, layout
3	3–4	Agent workflow, grounding, rules, review UI	Agent Framework, validation
4	4–5	Eval harness on CORD, FinTabNet and synthetic data; published numbers	Metrics, honest benchmarking
5	5–6	VM demo (option C), README, 3-minute video; optional Azure (option D)	Deployment, Bicep, managed identity
MVP done means: 5 doc types; ≥ 90% field F1 on synthetic data; near-zero hallucination rate; the demo story in §3 runs end to end on a public URL.

14. Pitching to founders
Hook: "LLMs read documents well but make up numbers. In finance one fake number is a compliance incident. LedgerLens grounds every value and proves the math."
Show, don't tell: the click-to-source highlight and the tampered statement failing reconciliation.
Numbers: your eval table vs. baselines. Be honest about weak spots (handwriting, low-quality scans).
Why open source: banks can self-host it; no documents leave their network (Foundry Local / on-prem).
Landscape to know: Azure AI Document Intelligence, AWS Textract, Google Document AI, Reducto, LlamaParse, Unstructured, Docling. Position LedgerLens as grounded + finance-validated + self-hostable, not as "better OCR".
Ask: feedback, design partners (a lender or an AP team), or a role building it.
15. Open questions
Is Foundry Local available on the demo VM's OS? If not, use Ollama there (that's the plan).
~~Which Floci-az services and SDK versions are verified?~~ Verified 2026-11-23: floci-az 0.17.0 with azure-storage-blob/queue async SDKs (blob upload/download, queue send/receive/delete, container/queue create). Storage is in-memory in this edition, so a restart empties it. Key Vault and Table not exercised yet.
Is a small vision LLM (e.g. Qwen2.5-VL) worth adding for checkboxes and handwriting? Decide after phase 4.
Docling (PyTorch) is deferred: the dev laptop has 8 GB RAM. Phase 2 uses pdfplumber + RapidOCR with our own deskew and column-aware Markdown (parse recall 99.7% on synthetic data, reports/eval_2026-11-26_parse.md). Docling stays as an optional comparison run on Kaggle.
~~Pin the floci/floci-az image~~ Pinned to 0.17.0.

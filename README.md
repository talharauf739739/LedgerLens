# LedgerLens

> **Every extracted number has a receipt.**

LedgerLens is open-source document intelligence for fintech. It turns messy financial documents (bank statements, invoices, receipts, pay slips, W-2s) into validated JSON. Every value is tied to where it appears on the page and is checked by deterministic finance rules. A value that can't be grounded is flagged for review, never guessed.

It is built to run fully locally and free (Foundry Local + Floci-az + open-source OCR), and to move to Azure AI Foundry with a config switch.

> **Status:** early design (v0.1). See [SPEC.md](SPEC.md) for the full specification. No code has landed yet.

## Why

Generic LLM extraction fails regulated finance teams in three ways:

- **Hallucination:** it returns values that aren't in the document.
- **Lost structure:** tables, multi-page statements and checkboxes get mangled.
- **No audit trail:** nobody can see where a number came from.

LedgerLens addresses each one. Every field carries a source span (page, bounding box, OCR text), a confidence score and a validation status.

## How it works

```
Preprocess → Parse/OCR → Classify → Extract → Validate → Ground & reconcile → Review
```

- **Parse/OCR:** Docling, PaddleOCR/RapidOCR, Tesseract, pypdfium2, pdfplumber
- **Agents:** Microsoft Agent Framework, as a deterministic workflow graph. Agents propose; code decides.
- **Validation:** plain-Python finance rules, e.g. `opening + credits − debits = closing`, invoice totals, IBAN mod-97
- **Grounding:** each value is fuzzy-matched to OCR spans; ungrounded values become `null` and are flagged
- **LLM backends:** Foundry Local, Ollama/vLLM, or Azure AI Foundry, behind one OpenAI-compatible interface

## Example output

```json
{
  "doc_type": "bank_statement",
  "fields": {
    "opening_balance": {
      "value": "1520.40",
      "confidence": 0.97,
      "source": {"page": 1, "bbox": [72, 110, 240, 124]},
      "status": "grounded"
    }
  },
  "validation": [
    {"rule": "balance_roll_forward", "status": "pass"}
  ]
}
```

Money is always stored as decimal strings, never floats.

## Planned stack

Python 3.12 · uv · FastAPI · Streamlit · Microsoft Agent Framework · Docling · Floci-az (local Azure emulation) · Presidio (PII masking) · OpenTelemetry · pytest · Docker Compose

## Roadmap

| Phase | Deliverable |
|-------|-------------|
| 0 | Repo, CI, docker-compose with Floci, Foundry Local "hello" |
| 1 | Synthetic generator for bank statements and invoices with ground truth |
| 2 | Parse/OCR → Markdown with bboxes; baseline LLM extraction |
| 3 | Agent workflow, grounding, rules, review UI |
| 4 | Eval harness on CORD, FinTabNet and synthetic data, with published numbers |
| 5 | VM demo, 3-minute video; optional Azure deployment |

## Data and privacy

LedgerLens uses **synthetic or public data only**. Datasets are downloaded into `data/`, which is git-ignored and never committed. No real personal financial documents.

## License

MIT (planned). Core dependencies must be MIT-compatible, so GPL/AGPL libraries are avoided.

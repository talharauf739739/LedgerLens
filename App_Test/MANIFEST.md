# Test records

SYNTHETIC TEST RECORD - fictitious data generated for LedgerLens testing. Not a real person.

Regenerate: `uv run python App_Test/make_test_records.py`

| File | Type | App mode | What to expect |
| --- | --- | --- | --- |
| `fintech/pdf/bank_statement_101_clean.pdf` | bank_statement | Read with OCR, or Full extraction (LLM) | eu_signed: all checks pass |
| `fintech/pdf/bank_statement_101_tampered.pdf` | bank_statement | Read with OCR, or Full extraction (LLM) | fails: balance_roll_forward, running_balance_consistency |
| `fintech/pdf/bank_statement_101_scanned.pdf` | bank_statement | Read with OCR, or Full extraction (LLM) | image-only PDF: OCR on every page; all checks pass |
| `fintech/pdf/bank_statement_102_clean.pdf` | bank_statement | Read with OCR, or Full extraction (LLM) | classic_us: all checks pass |
| `fintech/pdf/bank_statement_102_tampered.pdf` | bank_statement | Read with OCR, or Full extraction (LLM) | fails: balance_roll_forward, running_balance_consistency |
| `fintech/pdf/bank_statement_102_scanned.pdf` | bank_statement | Read with OCR, or Full extraction (LLM) | image-only PDF: OCR on every page; all checks pass |
| `fintech/images/bank_statement_101_photo.jpg` | bank_statement | Read with OCR, or Full extraction (LLM) | phone-style photo of page 1 (tilted, soft) |
| `fintech/images/bank_statement_101_scan.png` | bank_statement | Read with OCR, or Full extraction (LLM) | flatbed-style scan of page 1 |
| `fintech/images/bank_statement_400_all_pages.tif` | bank_statement | Read with OCR, or Full extraction (LLM) | multi-page TIFF: all 2 pages scanned |
| `fintech/pdf/invoice_201_clean.pdf` | invoice | Read with OCR, or Full extraction (LLM) | compact_gb: all checks pass |
| `fintech/pdf/invoice_201_tampered.pdf` | invoice | Read with OCR, or Full extraction (LLM) | fails: line_amounts, lines_sum_to_subtotal |
| `fintech/pdf/invoice_201_scanned.pdf` | invoice | Read with OCR, or Full extraction (LLM) | image-only PDF: OCR on every page; all checks pass |
| `fintech/pdf/invoice_202_clean.pdf` | invoice | Read with OCR, or Full extraction (LLM) | compact_nl: all checks pass |
| `fintech/pdf/invoice_202_tampered.pdf` | invoice | Read with OCR, or Full extraction (LLM) | fails: line_amounts, lines_sum_to_subtotal |
| `fintech/pdf/invoice_202_scanned.pdf` | invoice | Read with OCR, or Full extraction (LLM) | image-only PDF: OCR on every page; all checks pass |
| `fintech/pdf/invoice_203_clean.pdf` | invoice | Read with OCR, or Full extraction (LLM) | modern_gb: all checks pass |
| `fintech/pdf/invoice_203_tampered.pdf` | invoice | Read with OCR, or Full extraction (LLM) | fails: line_amounts, lines_sum_to_subtotal |
| `fintech/pdf/invoice_203_scanned.pdf` | invoice | Read with OCR, or Full extraction (LLM) | image-only PDF: OCR on every page; all checks pass |
| `fintech/images/invoice_201_photo.jpg` | invoice | Read with OCR, or Full extraction (LLM) | phone-style photo of page 1 (tilted, soft) |
| `fintech/images/invoice_201_scan.png` | invoice | Read with OCR, or Full extraction (LLM) | flatbed-style scan of page 1 |
| `fintech/images/invoice_403_all_pages.tif` | invoice | Read with OCR, or Full extraction (LLM) | multi-page TIFF: all 2 pages scanned |
| `healthcare/pdf/hospital_bill_1.pdf` | hospital_bill | Read with OCR | itemized charges; charges - payments - adjustments = balance |
| `healthcare/pdf/hospital_bill_2.pdf` | hospital_bill | Read with OCR | itemized charges; charges - payments - adjustments = balance |
| `healthcare/images/hospital_bill_1_photo.jpg` | hospital_bill | Read with OCR | phone-style photo |
| `healthcare/pdf/insurance_eob_1.pdf` | insurance_eob | Read with OCR | billed / allowed / plan paid / you owe per service, with totals |
| `healthcare/pdf/insurance_eob_2.pdf` | insurance_eob | Read with OCR | billed / allowed / plan paid / you owe per service, with totals |
| `healthcare/images/insurance_eob_1_photo.jpg` | insurance_eob | Read with OCR | phone-style photo |
| `healthcare/pdf/lab_report_1.pdf` | lab_report | Read with OCR | results with units, H/L flags and reference ranges |
| `healthcare/pdf/lab_report_2.pdf` | lab_report | Read with OCR | results with units, H/L flags and reference ranges |
| `healthcare/images/lab_report_1_photo.jpg` | lab_report | Read with OCR | phone-style photo |
| `healthcare/pdf/prescription_1.pdf` | prescription | Read with OCR | drugs, directions (Sig), quantity, refills |
| `healthcare/pdf/prescription_2.pdf` | prescription | Read with OCR | drugs, directions (Sig), quantity, refills |
| `healthcare/images/prescription_1_photo.jpg` | prescription | Read with OCR | phone-style photo |
| `healthcare/images/lab_report_2_scan.png` | lab_report | Read with OCR | flatbed-style scan |

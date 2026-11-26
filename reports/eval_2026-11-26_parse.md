# Parse recall: 2026-11-26

24 synthetic documents.

| Set | Docs | Pages | Field recall | Row recall | Sec/page (median) |
|---|---|---|---|---|---|
| bank_statement/clean | 6 | 9 | 55/55 (100.0%) | 220/220 (100.0%) | 0.10 |
| bank_statement/noisy | 6 | 9 | 55/55 (100.0%) | 220/220 (100.0%) | 7.45 |
| invoice/clean | 6 | 7 | 75/75 (100.0%) | 81/81 (100.0%) | 0.07 |
| invoice/noisy | 6 | 7 | 74/75 (98.7%) | 81/81 (100.0%) | 3.91 |

Missed fields (1, first 20):

- `invoice_00005_noisy:seller_iban_masked='FR14 3530 7151 50YU 3114 0983 800'`

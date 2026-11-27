"""Synthetic fintech and healthcare test records for the LedgerLens app.

Every name, number, ID and amount is fictitious (Faker + seeded random), and every page
says so. Regenerate with:

    uv run python App_Test/make_test_records.py

Fintech documents come from the project's generators (exact ground truth, so the app's
finance checks must pass on clean files and fail on tampered ones). Healthcare documents
are not a supported extraction type yet: use them with "Read with OCR".
"""

# ruff: noqa: S311  (test data, not cryptography)

from __future__ import annotations

import io
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium
from faker import Faker
from PIL import Image, ImageEnhance, ImageFilter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from synth import GENERATORS  # noqa: E402
from synth.noise import make_noisy  # noqa: E402

NOTICE = (
    "SYNTHETIC TEST RECORD - fictitious data generated for LedgerLens testing. Not a real person."
)
CENT = Decimal("0.01")


def money(d: Decimal) -> str:
    return f"${d.quantize(CENT):,.2f}"


def pct(d: Decimal, lo: float, hi: float, rng: random.Random) -> Decimal:
    return (d * Decimal(str(round(rng.uniform(lo, hi), 3)))).quantize(CENT)


# --- a tiny top-down page writer on ReportLab ---------------------------------------------


class Page:
    def __init__(self) -> None:
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=letter)
        self.w, self.h = letter
        self.y = 0.0
        self._start()

    def _start(self) -> None:
        self.c.setFont("Helvetica-Oblique", 7)
        self.c.setFillGray(0.45)
        self.c.drawString(40, self.h - 22, NOTICE)
        self.c.drawString(40, 20, NOTICE)
        self.c.setFillGray(0)
        self.y = 50.0

    def text(
        self, x: float, s: str, size: float = 10, bold: bool = False, right: bool = False
    ) -> None:
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        draw = self.c.drawRightString if right else self.c.drawString
        draw(x, self.h - self.y, s)

    def down(self, dy: float = 14) -> None:
        self.y += dy
        if self.y > self.h - 60:
            self.c.showPage()
            self._start()

    def rule(self) -> None:
        self.c.setLineWidth(0.5)
        self.c.line(40, self.h - self.y + 4, self.w - 40, self.h - self.y + 4)
        self.down(10)

    def row(self, cells: list[tuple[float, str, bool]], bold: bool = False) -> None:
        """cells: (x, text, right_aligned)"""
        for x, s, right in cells:
            self.text(x, s, bold=bold, right=right, size=9.5)
        self.down(14)

    def pairs(self, items: list[tuple[str, str]], x: float = 40, gap: float = 130) -> None:
        for label, value in items:
            self.text(x, label, bold=True, size=9.5)
            self.text(x + gap, value, size=9.5)
            self.down(13)

    def pdf(self) -> bytes:
        self.c.save()
        return self.buf.getvalue()


def header(p: Page, org: str, lines: list[str], title: str) -> None:
    p.text(40, org, size=15, bold=True)
    p.down(16)
    for line in lines:
        p.text(40, line, size=9)
        p.down(11)
    p.down(8)
    p.text(40, title, size=13, bold=True)
    p.down(20)


# --- healthcare -----------------------------------------------------------------------------

SERVICES = [
    ("99285", "Emergency department visit, high complexity", 1450, 2100),
    ("71046", "Chest X-ray, 2 views", 180, 420),
    ("80053", "Comprehensive metabolic panel", 95, 260),
    ("85025", "Complete blood count with differential", 45, 160),
    ("93005", "Electrocardiogram, tracing", 120, 340),
    ("96374", "IV push, single drug", 210, 480),
    ("J1100", "Dexamethasone injection, 1 mg", 12, 40),
    ("74177", "CT abdomen and pelvis with contrast", 1800, 3600),
    ("36415", "Venipuncture", 18, 45),
    ("99214", "Office visit, established patient", 160, 290),
]


def _patient(fake: Faker, rng: random.Random) -> dict[str, str]:
    dob = fake.date_of_birth(minimum_age=18, maximum_age=88)
    return {
        "name": fake.name(),
        "dob": dob.strftime("%m/%d/%Y"),
        "mrn": f"MRN-{rng.randint(10_000_000, 99_999_999)}",
        "address": fake.street_address(),
        "city": f"{fake.city()}, {fake.state_abbr()} {fake.zipcode()}",
    }


def hospital_bill(seed: int) -> bytes:
    fake, rng = Faker("en_US"), random.Random(seed)
    fake.seed_instance(seed)
    pt = _patient(fake, rng)
    dos = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    p = Page()
    hospital = f"{fake.last_name()} Regional Medical Center"
    header(
        p,
        hospital,
        [
            fake.street_address(),
            f"{fake.city()}, {fake.state_abbr()} {fake.zipcode()}",
            f"Billing: {fake.numerify('(###) ###-####')}",
        ],
        "Itemized Patient Statement",
    )
    p.pairs(
        [
            ("Patient", pt["name"]),
            ("Date of birth", pt["dob"]),
            ("Medical record no.", pt["mrn"]),
            ("Account no.", f"****{rng.randint(1000, 9999)}"),
            ("Date of service", dos.strftime("%m/%d/%Y")),
            ("Statement date", (dos + timedelta(days=rng.randint(20, 45))).strftime("%m/%d/%Y")),
            ("Insurance", f"{fake.company()} Health Plan"),
        ]
    )
    p.down(6)
    p.row(
        [
            (40, "Code", False),
            (95, "Description", False),
            (430, "Qty", True),
            (500, "Unit charge", True),
            (572, "Amount", True),
        ],
        bold=True,
    )
    p.rule()
    total = Decimal(0)
    for code, desc, lo, hi in rng.sample(SERVICES, rng.randint(5, 8)):
        qty = rng.choice([1, 1, 1, 2])
        unit = Decimal(rng.randint(lo * 100, hi * 100)) / 100
        amount = unit * qty
        total += amount
        p.row(
            [
                (40, code, False),
                (95, desc, False),
                (430, str(qty), True),
                (500, money(unit), True),
                (572, money(amount), True),
            ]
        )
    p.rule()
    paid = pct(total, 0.55, 0.75, rng)
    adjust = pct(total, 0.08, 0.15, rng)
    balance = total - paid - adjust
    for label, value in [
        ("Total charges", total),
        ("Insurance payments", -paid),
        ("Contractual adjustments", -adjust),
        ("Patient balance due", balance),
    ]:
        bold = label.startswith("Patient")
        p.row(
            [(430, label, True), (572, money(value) if value >= 0 else f"-{money(-value)}", True)],
            bold=bold,
        )
    p.down(10)
    p.text(
        40,
        f"Please pay by {(dos + timedelta(days=75)).strftime('%m/%d/%Y')}. "
        "Questions about this bill: call the billing office.",
        size=9,
    )
    return p.pdf()


def eob(seed: int) -> bytes:
    fake, rng = Faker("en_US"), random.Random(seed)
    fake.seed_instance(seed)
    pt = _patient(fake, rng)
    insurer = f"{fake.last_name()} Mutual Health Insurance"
    dos = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    p = Page()
    header(
        p,
        insurer,
        ["Member Services: 1-800-" + fake.numerify("###-####"), fake.city()],
        "Explanation of Benefits - THIS IS NOT A BILL",
    )
    p.pairs(
        [
            ("Member", pt["name"]),
            ("Member ID", f"XM{rng.randint(100_000_000, 999_999_999)}"),
            ("Group no.", f"G-{rng.randint(10000, 99999)}"),
            ("Claim no.", f"CLM-2026-{rng.randint(1_000_000, 9_999_999)}"),
            ("Provider", f"Dr. {fake.name()}"),
            ("Date(s) of service", dos.strftime("%m/%d/%Y")),
            ("Processed on", (dos + timedelta(days=rng.randint(10, 30))).strftime("%m/%d/%Y")),
        ]
    )
    p.down(6)
    p.row(
        [
            (40, "Service", False),
            (340, "Billed", True),
            (410, "Allowed", True),
            (480, "Plan paid", True),
            (572, "You owe", True),
        ],
        bold=True,
    )
    p.rule()
    sums = [Decimal(0)] * 4
    for _, desc, lo, hi in rng.sample(SERVICES, rng.randint(3, 6)):
        billed = Decimal(rng.randint(lo * 100, hi * 100)) / 100
        allowed = pct(billed, 0.45, 0.8, rng)
        plan = pct(allowed, 0.7, 0.9, rng)
        owe = allowed - plan
        for i, v in enumerate((billed, allowed, plan, owe)):
            sums[i] += v
        p.row(
            [
                (40, desc[:48], False),
                (340, money(billed), True),
                (410, money(allowed), True),
                (480, money(plan), True),
                (572, money(owe), True),
            ]
        )
    p.rule()
    p.row(
        [
            (40, "Totals", False),
            (340, money(sums[0]), True),
            (410, money(sums[1]), True),
            (480, money(sums[2]), True),
            (572, money(sums[3]), True),
        ],
        bold=True,
    )
    p.down(10)
    deductible = Decimal(rng.choice([500, 1000, 1500, 2500]))
    met = min(deductible, pct(deductible, 0.2, 1.0, rng))
    p.pairs(
        [
            ("Deductible met", f"{money(met)} of {money(deductible)}"),
            ("Your provider may bill you", money(sums[3])),
        ],
        gap=170,
    )
    return p.pdf()


LAB_TESTS = [
    ("Glucose", "mg/dL", 70, 99, 1),
    ("Sodium", "mmol/L", 136, 145, 0),
    ("Potassium", "mmol/L", 3.5, 5.1, 1),
    ("Creatinine", "mg/dL", 0.6, 1.3, 2),
    ("Hemoglobin", "g/dL", 12.0, 17.5, 1),
    ("White blood cells", "10^3/uL", 4.0, 11.0, 1),
    ("Platelets", "10^3/uL", 150, 400, 0),
    ("Total cholesterol", "mg/dL", 125, 200, 0),
    ("LDL cholesterol", "mg/dL", 0, 100, 0),
    ("HbA1c", "%", 4.0, 5.6, 1),
    ("TSH", "uIU/mL", 0.4, 4.0, 2),
]


def lab_report(seed: int) -> bytes:
    fake, rng = Faker("en_US"), random.Random(seed)
    fake.seed_instance(seed)
    pt = _patient(fake, rng)
    drawn = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    p = Page()
    header(
        p,
        f"{fake.last_name()} Diagnostics Laboratory",
        [fake.street_address(), f"CLIA ID: {rng.randint(10, 99)}D{rng.randint(1000000, 9999999)}"],
        "Laboratory Report",
    )
    p.pairs(
        [
            ("Patient", pt["name"]),
            ("Date of birth", pt["dob"]),
            ("Patient ID", pt["mrn"]),
            ("Ordering physician", f"Dr. {fake.name()}"),
            ("Collected", drawn.strftime("%m/%d/%Y") + " 08:" + f"{rng.randint(0, 59):02d}"),
            ("Reported", (drawn + timedelta(days=1)).strftime("%m/%d/%Y")),
        ]
    )
    p.down(6)
    p.row(
        [
            (40, "Test", False),
            (300, "Result", True),
            (330, "Flag", False),
            (380, "Units", False),
            (572, "Reference range", True),
        ],
        bold=True,
    )
    p.rule()
    for name, unit, lo, hi, dp in rng.sample(LAB_TESTS, rng.randint(7, 10)):
        span = hi - lo
        value = round(rng.uniform(lo - 0.25 * span, hi + 0.35 * span), dp)
        value = max(value, round(lo * 0.6, dp) if lo else round(hi * 0.4, dp))  # stays plausible
        flag = "H" if value > hi else "L" if value < lo else ""
        shown = f"{value:.{dp}f}"
        ref = f"{lo:.{dp}f} - {hi:.{dp}f}" if lo else f"< {hi:.{dp}f}"
        p.row(
            [
                (40, name, False),
                (300, shown, True),
                (330, flag, False),
                (380, unit, False),
                (572, ref, True),
            ]
        )
    p.rule()
    p.text(
        40,
        "H = above reference range, L = below. Results reviewed by the laboratory director.",
        size=9,
    )
    return p.pdf()


DRUGS = [
    ("Amoxicillin 500 mg capsule", "Take 1 capsule by mouth three times daily for 10 days", 30),
    ("Lisinopril 10 mg tablet", "Take 1 tablet by mouth once daily", 90),
    ("Metformin 500 mg tablet", "Take 1 tablet by mouth twice daily with meals", 180),
    ("Atorvastatin 20 mg tablet", "Take 1 tablet by mouth at bedtime", 90),
    ("Albuterol 90 mcg inhaler", "Inhale 2 puffs every 4-6 hours as needed", 1),
]


def prescription(seed: int) -> bytes:
    fake, rng = Faker("en_US"), random.Random(seed)
    fake.seed_instance(seed)
    pt = _patient(fake, rng)
    doctor = f"Dr. {fake.name()}, MD"
    p = Page()
    header(
        p,
        f"{fake.last_name()} Family Clinic",
        [
            fake.street_address(),
            f"{fake.city()}, {fake.state_abbr()}",
            f"Tel {fake.numerify('(###) ###-####')}",
        ],
        "Prescription",
    )
    p.pairs(
        [
            ("Patient", pt["name"]),
            ("Date of birth", pt["dob"]),
            ("Address", f"{pt['address']}, {pt['city']}"),
            ("Date", (date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))).strftime("%m/%d/%Y")),
        ]
    )
    p.down(8)
    for drug, sig, qty in rng.sample(DRUGS, rng.randint(1, 3)):
        p.text(40, "Rx", size=14, bold=True)
        p.text(70, drug, size=11, bold=True)
        p.down(15)
        p.pairs(
            [("Sig", sig), ("Quantity", str(qty)), ("Refills", str(rng.randint(0, 5)))],
            x=70,
            gap=80,
        )
        p.down(6)
    p.down(10)
    p.pairs([("Prescriber", doctor), ("Prescriber ID", f"TEST-{rng.randint(1000000, 9999999)}")])
    p.down(4)
    p.text(40, "Signature: ______________________", size=10)
    return p.pdf()


# --- "photos" and scans ---------------------------------------------------------------------


def photograph(pdf: bytes, seed: int, all_pages: bool = False) -> list[Image.Image]:
    """Render, tilt slightly, soften and tint: what a phone photo of the page looks like."""
    rng = random.Random(seed)
    doc = pdfium.PdfDocument(pdf)
    try:
        pages = list(doc) if all_pages else [doc[0]]
        out = []
        for page in pages:
            img = page.render(scale=170 / 72).to_pil().convert("RGB")
            img = img.rotate(rng.uniform(-2.0, 2.0), expand=True, fillcolor=(236, 233, 226))
            img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.7)))
            img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.92, 1.02))
            tint = Image.new("RGB", img.size, (255, 246, 228))
            out.append(Image.blend(img, tint, 0.08))
        return out
    finally:
        doc.close()


def save_images(pages: list[Image.Image], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = {".jpg": "JPEG", ".png": "PNG", ".tif": "TIFF"}[path.suffix]
    extra: dict[str, object] = {"quality": 82} if fmt == "JPEG" else {}
    if fmt == "TIFF":
        extra = {"save_all": True, "append_images": pages[1:], "compression": "tiff_lzw"}
    pages[0].save(path, fmt, **extra)


# --- build the folder -----------------------------------------------------------------------


@dataclass
class Entry:
    path: str
    kind: str
    mode: str
    expect: str


def main() -> int:
    entries: list[Entry] = []

    def put(rel: str, data: bytes, kind: str, mode: str, expect: str) -> None:
        path = HERE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entries.append(Entry(rel, kind, mode, expect))

    def put_photo(
        rel: str, pdf: bytes, seed: int, kind: str, mode: str, expect: str, all_pages: bool = False
    ) -> None:
        save_images(photograph(pdf, seed, all_pages), HERE / rel)
        entries.append(Entry(rel, kind, mode, expect))

    full = "Read with OCR, or Full extraction (LLM)"
    ocr = "Read with OCR"

    # Fintech: project generators, so expected results are exact.
    for doc_type, seeds in (("bank_statement", (101, 102)), ("invoice", (201, 202, 203))):
        for seed in seeds:
            name = f"{doc_type}_{seed}"
            clean = GENERATORS[doc_type](seed, name)
            tampered = GENERATORS[doc_type](seed, name, tamper=True)
            template = clean.meta.template
            put(
                f"fintech/pdf/{name}_clean.pdf",
                clean.pdf,
                doc_type,
                full,
                f"{template}: all checks pass",
            )
            put(
                f"fintech/pdf/{name}_tampered.pdf",
                tampered.pdf,
                doc_type,
                full,
                "fails: " + ", ".join(tampered.meta.expected_failures),
            )
            put(
                f"fintech/pdf/{name}_scanned.pdf",
                make_noisy(clean, seed).pdf,
                doc_type,
                full,
                "image-only PDF: OCR on every page; all checks pass",
            )
        first = GENERATORS[doc_type](seeds[0], f"{doc_type}_{seeds[0]}")
        put_photo(
            f"fintech/images/{doc_type}_{seeds[0]}_photo.jpg",
            first.pdf,
            seeds[0],
            doc_type,
            full,
            "phone-style photo of page 1 (tilted, soft)",
        )
        put_photo(
            f"fintech/images/{doc_type}_{seeds[0]}_scan.png",
            first.pdf,
            seeds[0] + 7,
            doc_type,
            full,
            "flatbed-style scan of page 1",
        )
        # The multi-page TIFF needs a document that really has several pages.
        candidates = [GENERATORS[doc_type](s, f"{doc_type}_{s}") for s in range(400, 440)]
        longest = max(candidates, key=lambda g: len(pdfium.PdfDocument(g.pdf)))
        n_pages = len(pdfium.PdfDocument(longest.pdf))
        put_photo(
            f"fintech/images/{longest.meta.id}_all_pages.tif",
            longest.pdf,
            seeds[0] + 3,
            doc_type,
            full,
            f"multi-page TIFF: all {n_pages} pages scanned",
            all_pages=True,
        )

    # Healthcare: new layouts, OCR only for now.
    makers = {
        "hospital_bill": (
            hospital_bill,
            "itemized charges; charges - payments - adjustments = balance",
        ),
        "insurance_eob": (eob, "billed / allowed / plan paid / you owe per service, with totals"),
        "lab_report": (lab_report, "results with units, H/L flags and reference ranges"),
        "prescription": (prescription, "drugs, directions (Sig), quantity, refills"),
    }
    for i, (name, (make, what)) in enumerate(makers.items()):
        for n in (1, 2):
            seed = 300 + 10 * i + n
            pdf = make(seed)
            put(f"healthcare/pdf/{name}_{n}.pdf", pdf, name, ocr, what)
        put_photo(
            f"healthcare/images/{name}_1_photo.jpg",
            make(300 + 10 * i + 1),
            seed + 50,
            name,
            ocr,
            "phone-style photo",
        )
    put_photo(
        "healthcare/images/lab_report_2_scan.png",
        lab_report(300 + 20 + 2),
        777,
        "lab_report",
        ocr,
        "flatbed-style scan",
    )

    lines = [
        "# Test records\n",
        f"{NOTICE}\n",
        "Regenerate: `uv run python App_Test/make_test_records.py`\n",
        "| File | Type | App mode | What to expect |",
        "| --- | --- | --- | --- |",
        *(f"| `{e.path}` | {e.kind} | {e.mode} | {e.expect} |" for e in entries),
        "",
    ]
    (HERE / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(entries)} files -> {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

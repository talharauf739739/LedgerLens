from eval.metrics import PRF, field_prf, iou, multiset_prf, overlaps, text_found


def test_text_found_exact_and_fuzzy() -> None:
    assert text_found("GB15 LLNS 1511 5055", "IBAN: GB15LLNS 1511 5055 2035 19")
    assert text_found("£8,699.54", "Opening balance £8,699.54")
    assert text_found("Cedarline Financial", "Cedarllne Financial")  # one OCR slip
    assert not text_found("£8,699.54", "Opening balance £9,123.00")
    assert not text_found("", "anything")


def test_boxes() -> None:
    assert overlaps((0, 0, 10, 10), (11, 0, 20, 10))  # within slack
    assert not overlaps((0, 0, 10, 10), (20, 0, 30, 10))
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == 50 / 150


def test_field_prf() -> None:
    assert field_prf("a", "a") == PRF(tp=1)
    assert field_prf("a", "b") == PRF(fp=1, fn=1)
    assert field_prf(None, "b") == PRF(fp=1)  # hallucinated a value
    assert field_prf("a", None) == PRF(fn=1)
    assert field_prf(None, None) == PRF()


def test_multiset_prf_counts_duplicates() -> None:
    r = multiset_prf(["x", "x", "y"], ["x", "z"])
    assert (r.tp, r.fp, r.fn) == (1, 1, 2)
    assert multiset_prf([], []).f1 == 1.0

from ledgerlens.cache import cache_key
from ledgerlens.db import Base, JobStatus


def test_cache_key_is_namespaced_versioned_and_stable() -> None:
    k1 = cache_key("ocr", "v1", b"page-bytes")
    assert k1.startswith("ll:ocr:v1:")
    assert k1 == cache_key("ocr", "v1", "page-bytes")  # str and bytes hash the same
    assert k1 != cache_key("ocr", "v2", b"page-bytes")  # version bump invalidates


def test_schema_tables_match_migration() -> None:
    assert set(Base.metadata.tables) == {"jobs", "audit_events"}
    assert [s.value for s in JobStatus] == [
        "queued",
        "running",
        "needs_review",
        "succeeded",
        "failed",
    ]

from tools.admin.export_model_migration_baseline import canonical_bytes, content_hash, reference_checks, safe_url


def test_canonical_hash_is_independent_of_dictionary_order():
    assert canonical_bytes({"b": 2, "a": 1}) == canonical_bytes({"a": 1, "b": 2})
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})


def test_safe_url_removes_query_and_fragment():
    assert safe_url("https://example.com/v1?token=secret#part") == "https://example.com/v1"


def test_reference_checks_report_orphans_without_failing_export():
    checks = reference_checks({
        "clothing_items": [{"id": "item-1"}],
        "recognition_records": [{"clothing_item_id": "missing"}],
    })
    result = next(row for row in checks if row["relationship"].startswith("recognition_records"))
    assert result["status"] == "warning"
    assert result["missing_count"] == 1

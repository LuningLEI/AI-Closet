from tools.evaluation.outerwear_shadow_annotation import representative_candidates, stratified_group_sample


def _row(outfit, outerwear, *, bulk="regular", title="Jacket", probability="0.2", rank="2", selected=False,
         production=False, masked=False, fit="1"):
    return {
        "source_outfit_id": outfit,
        "outerwear_id": outerwear,
        "outerwear_title": title,
        "inner_bulk": bulk,
        "probability": probability,
        "probability_rank": rank,
        "shadow_selected": str(selected),
        "production_present": str(production),
        "masked": str(masked),
        "fit_score": fit,
        "total_score": "4",
    }


def test_stratified_sampling_is_deterministic_and_preserves_rare_strata():
    rows = []
    for index in range(8):
        rows.extend([
            _row(f"regular-{index}", "NONE", title="No outerwear"),
            _row(f"regular-{index}", "j", selected=True),
        ])
    rows.extend([
        _row("rare", "NONE", bulk="bulky", title="No outerwear"),
        _row("rare", "c", bulk="bulky", title="Cardigan", selected=True, production=True),
    ])
    first = stratified_group_sample(rows, 3)
    second = stratified_group_sample(rows, 3)
    assert [group.source_outfit_id for group in first] == [group.source_outfit_id for group in second]
    assert "rare" in {group.source_outfit_id for group in first}


def test_representative_candidates_include_diagnostic_roles_without_duplicates():
    rows = [
        _row("o", "NONE", title="No outerwear", probability="0.1", rank="4"),
        _row("o", "selected", probability="0.3", rank="2", selected=True),
        _row("o", "top", probability="0.5", rank="1"),
        _row("o", "production", probability="0.08", rank="3", production=True),
        _row("o", "masked", probability="0", rank="5", masked=True, fit="-1"),
    ]
    result = representative_candidates(rows)
    assert [row["outerwear_id"] for row in result] == ["NONE", "selected", "top", "production", "masked"]

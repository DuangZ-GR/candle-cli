from migration.rewriter_benchmark import run_benchmark


def test_fixed_rewrite_benchmark_is_exact_and_syntax_safe():
    report = run_benchmark()

    assert report["case_count"] == 14
    assert report["expected_skip_count"] == 4
    assert report["exact_patch_accuracy"] == 1.0
    assert report["safe_skip_accuracy"] == 1.0
    assert report["syntax_valid_rate"] == 1.0
    assert report["passed"] is True

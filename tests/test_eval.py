from collections import Counter

from eval.run_eval import load_cases, score


def test_seeded_eval_metrics():
    cases = load_cases()
    counts = Counter(case["category"] for case in cases)
    assert len(cases) == 25
    assert set(counts) == {"dependency", "flaky_test", "config", "timeout", "other"}
    assert all(count == 5 for count in counts.values())

    with_memory = score(cases, use_memory=True)
    without_memory = score(cases, use_memory=False)
    assert with_memory["top1_accuracy"] == 1
    assert with_memory["retrieval_hit_rate_at_3"] == 1
    assert with_memory["fix_success"] == 1
    assert with_memory["decline_rate_on_ambiguous"] == 1
    assert with_memory["false_decline_rate"] == 0
    assert without_memory["top1_accuracy"] == 0
    assert without_memory["decline_rate_on_ambiguous"] == 1
    assert without_memory["misses"]

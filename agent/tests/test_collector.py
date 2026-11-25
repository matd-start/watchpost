from agent.collector import collect


def test_collect_returns_the_three_percent_metrics() -> None:
    sample = collect()
    assert set(sample) == {"cpu.percent", "mem.percent", "disk.percent"}


def test_percentages_are_in_range() -> None:
    for metric, value in collect().items():
        assert 0 <= value <= 100, f"{metric} fuera de rango: {value}"

from __future__ import annotations

from app import visitor_counter


def test_counter_state_returns_shared_aggregate_after_increment(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_counter_value(key: str, *, increment: bool) -> int:
        assert key == "total"
        calls.append(increment)
        return 1 if increment else 27

    monkeypatch.setattr(visitor_counter, "_counter_value", fake_counter_value)

    value, incremented = visitor_counter._counter_state("total", increment=True)

    assert calls == [True, False]
    assert value == 27
    assert incremented is True


def test_counter_state_reads_without_increment(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_counter_value(key: str, *, increment: bool) -> int:
        assert key == "total"
        calls.append(increment)
        return 12

    monkeypatch.setattr(visitor_counter, "_counter_value", fake_counter_value)

    value, incremented = visitor_counter._counter_state("total", increment=False)

    assert calls == [False]
    assert value == 12
    assert incremented is False

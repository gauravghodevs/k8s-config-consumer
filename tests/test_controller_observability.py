from controller import rollout_guard


def test_successful_rollout_updates_metrics(tmp_path, monkeypatch):
    controller = rollout_guard.PromotionController(
        str(tmp_path / "candidate.yaml")
    )

    monkeypatch.setattr(
        controller,
        "start_metrics_server",
        lambda: None,
    )

    monkeypatch.setattr(
        controller,
        "validate_candidate",
        lambda: None,
    )

    monkeypatch.setattr(
        controller,
        "promote",
        lambda: None,
    )

    before_total = rollout_guard.rollouts_total._value.get()
    before_success = rollout_guard.rollouts_success_total._value.get()
    before_halted = rollout_guard.rollouts_halted_total._value.get()
    before_rollbacks = rollout_guard.rollbacks_total._value.get()

    result = controller.run()

    assert result == 0
    assert rollout_guard.rollouts_total._value.get() == before_total + 1
    assert rollout_guard.rollouts_success_total._value.get() == before_success + 1
    assert rollout_guard.rollouts_halted_total._value.get() == before_halted
    assert rollout_guard.rollbacks_total._value.get() == before_rollbacks


def test_failed_rollout_updates_halt_and_rollback_metrics(
    tmp_path,
    monkeypatch,
):
    controller = rollout_guard.PromotionController(
        str(tmp_path / "candidate.yaml")
    )

    monkeypatch.setattr(
        controller,
        "start_metrics_server",
        lambda: None,
    )

    monkeypatch.setattr(
        controller,
        "validate_candidate",
        lambda: (_ for _ in ()).throw(
            RuntimeError("deterministic test failure")
        ),
    )

    rollback_called = []

    monkeypatch.setattr(
        controller,
        "rollback",
        lambda: rollback_called.append(True),
    )

    monkeypatch.setattr(
        controller,
        "transition",
        lambda state: None,
    )

    before_total = rollout_guard.rollouts_total._value.get()
    before_success = rollout_guard.rollouts_success_total._value.get()
    before_halted = rollout_guard.rollouts_halted_total._value.get()
    before_rollbacks = rollout_guard.rollbacks_total._value.get()

    result = controller.run()

    assert result == 2
    assert rollback_called == [True]

    assert rollout_guard.rollouts_total._value.get() == before_total + 1
    assert rollout_guard.rollouts_success_total._value.get() == before_success
    assert rollout_guard.rollouts_halted_total._value.get() == before_halted + 1
    assert rollout_guard.rollbacks_total._value.get() == before_rollbacks + 1


def test_rollout_duration_is_recorded(tmp_path, monkeypatch):
    controller = rollout_guard.PromotionController(
        str(tmp_path / "candidate.yaml")
    )

    monkeypatch.setattr(
        controller,
        "start_metrics_server",
        lambda: None,
    )

    monkeypatch.setattr(
        controller,
        "validate_candidate",
        lambda: None,
    )

    monkeypatch.setattr(
        controller,
        "promote",
        lambda: None,
    )

    before_count = (
        rollout_guard.rollout_duration_seconds
        ._sum.get()
    )

    controller.run()

    after_count = (
        rollout_guard.rollout_duration_seconds
        ._sum.get()
    )

    assert after_count > before_count

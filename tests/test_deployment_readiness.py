from controller.rollout_guard import PromotionController


def _controller(tmp_path):
    return PromotionController(
        str(tmp_path / "candidate.yaml")
    )


def test_wait_for_deployment_ready_succeeds_when_generation_and_replicas_match(
    tmp_path,
    monkeypatch,
):
    controller = _controller(tmp_path)

    monkeypatch.setattr(
        controller,
        "run_cmd_raw",
        lambda command: b"2 2 1 1 1 1",
    )

    controller.wait_for_deployment_ready(
        "blast-cell-1",
        timeout=1,
    )


def test_wait_for_deployment_ready_retries_until_ready(
    tmp_path,
    monkeypatch,
):
    controller = _controller(tmp_path)

    outputs = iter(
        [
            b"2 1 1 1 0 0",
            b"2 2 1 1 1 1",
        ]
    )

    monkeypatch.setattr(
        controller,
        "run_cmd_raw",
        lambda command: next(outputs),
    )

    monkeypatch.setattr(
        "controller.rollout_guard.time.sleep",
        lambda seconds: None,
    )

    controller.wait_for_deployment_ready(
        "blast-cell-1",
        timeout=5,
    )


def test_wait_for_deployment_ready_times_out_when_replicas_never_match(
    tmp_path,
    monkeypatch,
):
    controller = _controller(tmp_path)

    monkeypatch.setattr(
        controller,
        "run_cmd_raw",
        lambda command: b"2 2 1 1 0 0",
    )

    clock = iter([0, 2, 4, 6])

    monkeypatch.setattr(
        "controller.rollout_guard.time.time",
        lambda: next(clock),
    )

    monkeypatch.setattr(
        "controller.rollout_guard.time.sleep",
        lambda seconds: None,
    )

    try:
        controller.wait_for_deployment_ready(
            "blast-cell-1",
            timeout=5,
        )
    except RuntimeError as error:
        assert (
            "did not become ready in blast-cell-1"
            in str(error)
        )
    else:
        raise AssertionError(
            "Deployment readiness unexpectedly succeeded"
        )

from pathlib import Path


def test_workflow_treats_an_empty_fast_monitor_heartbeat_as_unhealthy_not_an_error():
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/transfer-bot.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "if updated:" in text
    assert "AttributeError" in text
    assert "steps.fast_monitor.outputs.healthy != 'true'" in text

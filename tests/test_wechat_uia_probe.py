import subprocess

import pytest

from scripts.probe_wechat_uia import classify, probe


def window(kind="target", **kwargs):
    return {"kind": kind, "controls": {}, "truncated": False, "error": None, **kwargs}


def test_window_shell_does_not_pass_as_readable():
    assert classify([window(controls={"Pane": 2, "Button": 4, "TitleBar": 1})]) == "message_controls_unavailable"


def test_text_alone_does_not_prove_messages():
    assert classify([window(controls={"Text": 20})]) == "message_controls_unavailable"


def test_message_candidates_require_real_message_test():
    assert classify([window(controls={"List": 1, "ListItem": 5, "Text": 10})]) == "requires_message_verification"


def test_target_absent_or_ambiguous_never_passes():
    assert classify([window("main")]) == "target_window_missing"
    assert classify([window(), window()]) == "target_window_ambiguous"


@pytest.mark.parametrize("fields", [{"truncated": True}, {"error": "uia_error"}])
def test_incomplete_scan_is_inconclusive(fields):
    assert classify([window(**fields)]) == "scan_inconclusive"


def test_hung_provider_is_bounded_and_does_not_leak_output():
    def hung(*args, **kwargs):
        assert kwargs["timeout"] == 15
        raise subprocess.TimeoutExpired("probe", 15, output="PRIVATE CHAT")
    result = probe("test-group", timeout=15, runner=hung, platform="win32")
    assert result == {"status": "probe_timeout", "windows": []}
    assert "PRIVATE" not in str(result)


def test_unsupported_platform_does_not_spawn():
    def forbidden(*args, **kwargs):
        pytest.fail("must not start UIA on unsupported platform")
    assert probe("test-group", runner=forbidden, platform="linux")["status"] == "unsupported_platform"


def test_provider_failure_does_not_expose_stderr():
    def failed(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "PRIVATE CHAT")
    assert probe("test-group", runner=failed, platform="win32") == {"status": "probe_failed", "windows": []}


def test_valid_empty_result_reports_missing_target():
    def empty(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, '{"windows":[],"processes":[]}', '')
    assert probe("test-group", runner=empty, platform="win32")["status"] == "target_window_missing"

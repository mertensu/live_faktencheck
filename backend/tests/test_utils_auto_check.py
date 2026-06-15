from backend.utils import auto_check_enabled


def test_enabled_when_session_flag_true_even_without_env(monkeypatch):
    monkeypatch.delenv("AUTO_APPROVE", raising=False)
    assert auto_check_enabled({"auto_check": True}) is True


def test_disabled_when_both_false(monkeypatch):
    monkeypatch.delenv("AUTO_APPROVE", raising=False)
    assert auto_check_enabled({"auto_check": False}) is False
    assert auto_check_enabled(None) is False
    assert auto_check_enabled({}) is False  # key absent


def test_env_var_still_forces_enabled(monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE", "true")
    assert auto_check_enabled({"auto_check": False}) is True
    assert auto_check_enabled(None) is True

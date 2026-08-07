from eu5lint.gameversion import (VERIFIED_GAME_VERSION, parse_version,
                                 version_notice)


def test_parse_version():
    assert parse_version("1.3.11") == (1, 3, 11)
    assert parse_version("1.4") == (1, 4)
    assert parse_version("1.4.0 beta") == (1, 4, 0)
    assert parse_version("garbage") is None


def test_notice_warns_when_game_newer():
    message, is_warning = version_notice("9.9.9")
    assert is_warning
    assert "provisional" in message


def test_notice_quiet_on_verified_version():
    message, is_warning = version_notice(VERIFIED_GAME_VERSION)
    assert not is_warning
    assert VERIFIED_GAME_VERSION in message


def test_notice_quiet_on_older_game():
    message, is_warning = version_notice("1.0.0")
    assert not is_warning


def test_notice_handles_unknown():
    message, is_warning = version_notice(None)
    assert not is_warning
    assert "unknown" in message

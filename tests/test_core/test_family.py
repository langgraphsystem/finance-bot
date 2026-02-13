"""Tests for family management — invite code generation."""

from src.core.family import generate_invite_code


def test_invite_code_length():
    """Invite code should be exactly 8 characters."""
    code = generate_invite_code()
    assert len(code) == 8


def test_invite_code_unique():
    """Multiple generated codes should all be unique."""
    codes = [generate_invite_code() for _ in range(100)]
    assert len(set(codes)) == 100


def test_invite_code_uppercase():
    """Invite code should be fully uppercased."""
    code = generate_invite_code()
    assert code == code.upper()


def test_invite_code_is_string():
    """Invite code should be a string."""
    code = generate_invite_code()
    assert isinstance(code, str)


def test_invite_code_no_whitespace():
    """Invite code should not contain whitespace."""
    for _ in range(50):
        code = generate_invite_code()
        assert " " not in code
        assert "\n" not in code
        assert "\t" not in code

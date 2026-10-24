import pytest
from coursevault.backend import safe_name, safe_slug, validate_origin, Session

def test_safe_name_rejects_path_chars():
    assert safe_name("Intro/Week: 1?") == "Intro_Week_ 1_"
    assert safe_name("../") == "_"
    assert safe_name("") == "untitled"

def test_slug():
    assert safe_slug("Module 1 / Video") == "Module-1-Video"

@pytest.mark.parametrize("value", [
    "http://example.com", "file:///etc/passwd", "https://example.com/path",
    "https://user:pass@example.com", "https://example.com/?q=1",
])
def test_origin_rejects_unsafe_input(value):
    with pytest.raises(ValueError):
        validate_origin(value)

def test_origin_accepts_https():
    assert validate_origin("https://baumancollege.instructure.com/") == "https://baumancollege.instructure.com"

def test_session_does_not_require_login_on_construction(tmp_path):
    s = Session(state_file=tmp_path / "session.json")
    assert not s.state_file.exists()

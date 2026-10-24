from coursevault.export import safe_name

def test_safe_name():
    assert safe_name("A/B: C?") == "A_B_ C_"
    assert safe_name("") == "untitled"

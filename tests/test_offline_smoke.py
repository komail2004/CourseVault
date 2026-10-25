from coursevault.offline import viewer, name

def test_viewer():
    assert 'OFFLINE' in viewer('Course', [])

def test_name():
    assert '/' not in name('../foo.pdf')

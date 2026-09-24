from phase7.tokenizer import tokenize_cli
def test_quoted_value_stays_one_token():
    assert tokenize_cli('set banner "hello world"') == ["set","banner","hello world"]
def test_raw_whitespace_is_normalized():
    assert tokenize_cli("  set   ssh   version 2  ") == ["set","ssh","version","2"]

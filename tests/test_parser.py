from bot.parser import parse_transfer

def test_fabrizio_to_here_we_go():
    x = parse_transfer("🚨 Antonio Silva to Bournemouth, here we go! Deal now signed between clubs.")
    assert x["player"] == "Antonio Silva"
    assert x["to_club"] == "Bournemouth"

def test_ambiguous_is_rejected():
    x = parse_transfer("Here we go! The transfer no one saw coming.")
    assert x["player"] is None

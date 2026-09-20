"""Red-flag pattern tests — EN + HI + Hinglish, and benign-text false positives."""
from server.redflags import scan


def ids(text):
    return {h["id"] for h in scan(text)}


def test_english_playbook():
    fired = ids(
        "Join our VIP tips group! Guaranteed 30% monthly returns, double your money. "
        "Act fast — last chance today. Withdrawal blocked, pay unlock fee to release "
        "your money. Transfer to my personal account. Don't tell anyone. "
        "Download the app from link (APK). SEBI registered advisor. "
        "Sending profit screenshot as proof.")
    for want in ["tips_group", "guaranteed_returns", "urgency", "unlock_fees",
                 "personal_account", "secrecy", "sideload_app", "sebi_claim",
                 "fake_profit_proof"]:
        assert want in fired, f"missing {want}: {fired}"


def test_hindi_playbook():
    fired = ids(
        "टेलीग्राम ग्रुप जॉइन करो! पक्का रिटर्न, पैसा डबल। आज ही निवेश करें — "
        "आखिरी मौका। निकासी ब्लॉक है, फीस जमा करो। मेरे खाते में पैसे भेजो। "
        "किसी को न बताएं। ऐप डाउनलोड करो। सेबी रजिस्टर्ड सलाहकार। मुनाफे का स्क्रीनशॉट भेज रहा हूँ।")
    for want in ["tips_group", "guaranteed_returns", "urgency", "unlock_fees",
                 "personal_account", "secrecy", "sideload_app", "sebi_claim",
                 "fake_profit_proof"]:
        assert want in fired, f"missing {want}: {fired}"


def test_hinglish_unlock_fee():
    assert "unlock_fees" in ids("Bhai withdrawal atka hai, tax deposit karo tabhi release hoga")


def test_celebrity_bait():
    assert "celebrity_bait" in ids("Strategy Rakesh Jhunjhunwala jaisi hai")
    assert "celebrity_bait" in ids("MD ka video message dekha? deepfake nahi, real hai")


def test_benign_text_stays_clean():
    benign = ("Zerodha Broking Limited is a registered stock broker. Open a demat "
              "account through their official app. Mutual fund investments are subject "
              "to market risks; past performance does not guarantee future returns. "
              "Read all scheme related documents carefully.")
    fired = ids(benign)
    # the market-risk disclaimer must not trip guaranteed_returns; official-app
    # mention must not trip sideload_app
    assert "guaranteed_returns" not in fired
    assert "sideload_app" not in fired
    assert "unlock_fees" not in fired
    assert "personal_account" not in fired


def test_no_score_ever():
    """Supporting layer must expose phrases+reasons, never numbers (DECISIONS §4)."""
    for h in scan("guaranteed returns, act fast, pay unlock fee"):
        assert set(h.keys()) == {"id", "label", "why", "matched"}
        assert isinstance(h["label"], dict) and "en" in h["label"] and "hi" in h["label"]

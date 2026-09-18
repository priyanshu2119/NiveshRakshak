"""Linguistic red-flag detection — SUPPORTING evidence only.

Design rules (docs/ADVERSARIAL-REVIEW.md scenario 5):
  - never produces a numeric score (nothing to optimize against)
  - can never raise or lower the headline verdict (verdict.py enforces)
  - renders as readable phrase chips + plain-language explanations
  - bilingual EN/HI patterns; scam scripts are highly repetitive, so a
    curated pattern list catches the median case without an LLM

Each pattern set is grounded in the documented scam playbook (brief §2):
tips-groups → fake profit screenshots → fake app → blocked withdrawal →
"unlock fees/taxes" → personal-account collection → urgency → secrecy.
"""
import re

FLAGS = [
    {
        "id": "guaranteed_returns",
        "en": ("Guaranteed / unusually specific returns",
               "No legitimate investment can promise fixed high returns. "
               "SEBI-registered advisors are not allowed to guarantee profits."),
        "hi": ("गारंटीड / तय रिटर्न का वादा",
               "कोई भी वैध निवेश तय ऊँचा रिटर्न नहीं दे सकता। SEBI-पंजीकृत सलाहकार लाभ की गारंटी नहीं दे सकते।"),
        "re": re.compile(
            r"(guarantee\w*[\s-]+(?:return|profit|income)|assured[\s-]+(?:return|profit|income)|"
            r"double[\s-]+(?:your|ur)?[\s-]*(?:money|investment|amount)|"
            r"(?:2x|3x|10x)[\s-]+(?:your|ur)?[\s-]*money|"
            r"\d{1,3}\s*%\s*(?:per|every|in)?\s*(?:month|week|day|monthly|weekly|daily|महीन|साल)|"
            r"पक्क[ाे]\s*(?:रिटर्न|फायद[ाे]|मुनाफ[ाे]|लाभ)|डबल|तिगुना|"
            r"(?:रिटर्न|मुनाफा|फायदा)\s*(?:की\s*)?गारंटी|फिक्स(?:ड)?\s*रिटर्न)", re.I),
    },
    {
        "id": "urgency",
        "en": ("High-pressure urgency",
               "Scammers manufacture deadlines so you pay before you can think or verify."),
        "hi": ("जल्दबाजी का दबाव",
               "ठग जान-बूझकर नकली डेडलाइन बनाते हैं ताकि आप सोच-समझ या जांच से पहले पैसे भेज दें।"),
        "re": re.compile(
            r"(act[\s-]+fast|hurry[\s-]+up|last[\s-]+(?:chance|day|date)|closing[\s-]+(?:today|soon|tomorrow)|"
            r"limited[\s-]+(?:period|time|slots?|seats?|offer)|offer[\s-]+(?:band|close|khatam|expire)|"
            r"today[\s-]+only|before[\s-]+\d|\d[\s-]*(?:baje|pm|am)[\s-]+(?:se[\s-]+pehle|ke[\s-]+andar)|"
            r"आज[\s-]+ही|तुरंत|जल्दी[\s-]+कर[ोे]|आखिरी[\s-]+(?:मौका|तारीख|दिन)|"
            r"सीमित[\s-]+(?:समय|ऑफर)|देर[\s-]+(?:मत[\s-]+)?कर[ोे]|समय[\s-]+खत्म)", re.I),
    },
    {
        "id": "unlock_fees",
        "en": ("Fees/taxes demanded to release money",
               "The 'withdrawal blocked, pay fee/tax/margin to unlock' demand is the "
               "single most documented move in fake-trading-app scams. Real brokers "
               "never ask you to deposit more money to withdraw your own."),
        "hi": ("पैसे निकालने के लिए फीस/टैक्स की मांग",
               "‘निकासी ब्लॉक है, खोलने के लिए फीस/टैक्स/मार्जिन जमा करो’ — नकली ट्रेडिंग ऐप घोटालों की सबसे पहचानी गई चाल। "
               "असली ब्रोकर अपना पैसा निकालने के लिए कभी अतिरिक्त जमा नहीं मांगता।"),
        "re": re.compile(
            r"(unlock(?:ing)?[\s-]+(?:fee|charge|amount|code|karne)|"
            r"withdraw(?:al)?[\s-]+(?:fee|charge|tax|block\w*|frozen|froze|stuck|hold|pending|atka\w*|fail\w*|reject\w*|deduct\w*|nahi|nhi)|"
            r"(?:release|unblock|unfreeze)[\s-]+(?:your|the|my)?[\s-]*(?:money|funds?|amount|payment|account|hoga|hogi|karo|karne)|"
            r"margin[\s-]+(?:top[\s-]?up|money)[\s-]+(?:add|pay|deposit|karo|dalo)?|"
            r"(?:pay|deposit|transfer|bharo|jama)[\s-]+(?:the[\s-]+)?(?:tax|gst|tds|fee|charges?)|"
            r"(?:tax|gst|tds|fee|charges?)[\s-]+(?:deposit|pay|bharo|jama|karo|dena|de[\s-]+do)|"
            r"निकासी[\s-]+(?:ब्लॉक|रोक|अटक)|फ्रीज|जमा[\s-]+कर[ोे]|फीस[\s-]+(?:भर[ोे]|जमा)|"
            r"टैक्स[\s-]+(?:भर[ोे]|जमा|देना)|पैसे[\s-]+(?:निकालने|रिलीज)[\s-]+के[\s-]+लिए|"
            r"मार्जिन[\s-]+(?:टॉप[\s-]?अप|जमा)|अनलॉक[\s-]+(?:फीस|चार्ज|कर[ोे]))", re.I),
    },
    {
        "id": "personal_account",
        "en": ("Payment into a personal account",
               "Registered intermediaries must collect investment money through "
               "NPCI-verified @valid UPI handles or institutional bank accounts — "
               "never a personal account."),
        "hi": ("व्यक्तिगत खाते में पैसे की मांग",
               "पंजीकृत संस्थान निवेश का पैसा सिर्फ NPCI-सत्यापित @valid UPI हैंडल या संस्थागत बैंक खाते में ले सकते हैं — "
               "कभी किसी व्यक्तिगत खाते में नहीं।"),
        "re": re.compile(
            r"(personal[\s-]+(?:account|upi|khata|vpa)|(?:my|mere|hamare)[\s-]+(?:account|khata)[\s-]+(?:mein|me|par|to|में|पर)|"
            r"transfer[\s-]+to[\s-]+my|individual[\s-]+account|pay[\s-]+to[\s-]+my[\s-]+upi|"
            r"मेरे[\s-]+(?:खाते|अकाउंट|यूपीआई)|व्यक्तिगत[\s-]+खात[ाे]|पर्सनल[\s-]+(?:अकाउंट|खात[ाे])|"
            r"अपने[\s-]+(?:दोस्त|परिचित|रिश्तेदार)[\s-]+के[\s-]+खाते)", re.I),
    },
    {
        "id": "tips_group",
        "en": ("Tips-group / channel funnel",
               "WhatsApp/Telegram 'tips' groups with profit screenshots are the "
               "documented entry point of the investment-scam playbook."),
        "hi": ("टिप्स ग्रुप / चैनल का जाल",
               "मुनाफे के स्क्रीनशॉट वाले WhatsApp/Telegram ‘टिप्स’ ग्रुप निवेश घोटालों का पहला कदम होते हैं।"),
        "re": re.compile(
            r"(tips?[\s-]+group|free[\s-]+(?:tips|calls|stocks?|calls)|telegram[\s-]+(?:group|channel|link|join)|"
            r"whatsapp[\s-]+group[\s-]+(?:join|link)|join[\s-]+(?:my|our|this)[\s-]+(?:group|channel|telegram|whatsapp)|"
            r"vip[\s-]+(?:group|channel|tips)|premium[\s-]+(?:group|calls|tips)|"
            r"टिप्स[\s-]+ग्रुप|फ्री[\s-]+टिप्स|टेलीग्राम[\s-]+(?:ग्रुप|चैनल|जॉइन)|व्हाट्सएप[\s-]+ग्रुप|"
            r"ग्रुप[\s-]+जॉइन|वीआईपी[\s-]+(?:ग्रुप|चैनल))", re.I),
    },
    {
        "id": "celebrity_bait",
        "en": ("Celebrity / brand name-drop",
               "Impersonation of famous investors or brands (often via deepfake "
               "video) is used to borrow trust the sender has not earned."),
        "hi": ("मशहूर व्यक्ति / ब्रांड का नाम",
               "प्रसिद्ध निवेशकों या ब्रांड्स की नकल (अक्सर डीपफेक वीडियो से) भरोसा उधार लेने के लिए की जाती है।"),
        "re": re.compile(
            r"(rakesh[\s-]+jhunjhunwala|jhunjhunwala|deepfake|"
            r"(?:official|verified|real)[\s-]+(?:page|channel|group|account)[\s-]+of|"
            r"as[\s-]+seen[\s-]+on[\s-]+(?:tv|news)|"
            r"(?:md|ceo|director|founder)[\s-]+(?:ka|of|ji)?[\s-]+(?:video|message|call|whatsapp)|"
            r"राकेश[\s-]+झुनझुनवाला|डीपफेक|(?:सेलिब्रिटी|मशहूर)[\s-]+(?:निवेशक|व्यक्ति))", re.I),
    },
    {
        "id": "secrecy",
        "en": ("Secrecy pressure",
               "'Don't tell anyone' isolates you from the people most likely to spot the scam."),
        "hi": ("चुप रहने का दबाव",
               "‘किसी को बताना मत’ आपको उन लोगों से अलग करता है जो घोटाला पहचान सकते हैं।"),
        "re": re.compile(
            r"(don'?t[\s-]+(?:tell|share|discuss)|keep[\s-]+(?:it[\s-]+)?secret|kisi[\s-]+ko[\s-]+mat[\s-]+bata(?:na|o)?|"
            r"family[\s-]+(?:ko|se)?[\s-]+mat|बता(?:ना|ओ)?[\s-]+मत|किसी[\s-]+को[\s-]+न[\s-]+बताएँ?|"
            r"गुप्त[\s-]+(?:रख[ोे]|जानकारी)|सीक्रेट[\s-]+(?:रख[ोे]|ग्रुप))", re.I),
    },
    {
        "id": "sideload_app",
        "en": ("App install from link / APK",
               "Fake trading apps are distributed as APK links or side-loads, "
               "never through official app-store listings of real brokers."),
        "hi": ("लिंक / APK से ऐप इंस्टॉल",
               "नकली ट्रेडिंग ऐप APK लिंक से बांटे जाते हैं, असली ब्रोकर के आधिकारिक ऐप-स्टोर लिस्टिंग से नहीं।"),
        "re": re.compile(
            r"(\bapk\b|install[\s-]+(?:this|the)[\s-]+app|"
            r"download[\s-]+(?:the|our|this)[\s-]+app[\s-]+(?:from|link|here|apk)|"
            r"app[\s-]+(?:download|install)[\s-]+(?:karo|karne|link)|"
            r"ऐप[\s-]+(?:डाउनलोड|इंस्टॉल|लगाओ)|एपीके[\s-]+(?:फाइल|डाउनलोड|भेज)|\bएपीके\b)", re.I),
    },
    {
        "id": "sebi_claim",
        "en": ("'SEBI registered' claimed in chat",
               "Registration is proved by the payment channel and the official "
               "registry — not by a claim typed in a message. Impersonators quote "
               "real registration numbers that belong to someone else."),
        "hi": ("चैट में ‘SEBI रजिस्टर्ड’ होने का दावा",
               "पंजीकरण का सबूत भुगतान चैनल और आधिकारिक रजिस्ट्री है — मैसेज में लिखा दावा नहीं। "
               "नकलची अक्सर किसी और का असली रजिस्ट्रेशन नंबर उद्धृत करते हैं।"),
        "re": re.compile(
            r"(sebi[\s-]+(?:registered|approved|certified|verified|license[d]?|regd)|"
            r"(?:registered|approved|certified)[\s-]+(?:with|by)[\s-]+sebi|"
            r"सेबी[\s-]+(?:रजिस्टर्ड|पंजीकृत|मान्यता[\s-]+प्राप्त|सर्टिफाइड|वेरिफाइड)|"
            r"सेबी[\s-]+द्वारा[\s-]+(?:पंजीकृत|मान्यता))", re.I),
    },
    {
        "id": "fake_profit_proof",
        "en": ("Profit screenshots / statements as proof",
               "Fabricated profit screenshots and PDF 'statements' are the "
               "trust-building step of the playbook; a real exchange statement "
               "comes from the broker's own app, not a chat forward."),
        "hi": ("मुनाफे के स्क्रीनशॉट / स्टेटमेंट ‘सबूत’ के रूप में",
               "बनाए हुए प्रॉफिट स्क्रीनशॉट और PDF स्टेटमेंट भरोसा बनाने का कदम हैं; "
               "असली स्टेटमेंट ब्रोकर के अपने ऐप से आता है, चैट फॉरवर्ड से नहीं।"),
        "re": re.compile(
            r"(profit[\s-]+screenshot|screenshot[\s-]+(?:of|bhej|dekho|भेज)|"
            r"(?:daily|weekly|monthly)[\s-]+profit[\s-]+(?:proof|screenshot|report)|"
            r"statement[\s-]+(?:pdf|bhej|देखो)|"
            r"मुनाफे[\s-]+का[\s-]+(?:स्क्रीनशॉट|सबूत|प्रूफ)|प्रॉफिट[\s-]+(?:स्क्रीनशॉट|सबूत)|"
            r"कमाई[\s-]+का[\s-]+(?:सबूत|स्क्रीनशॉट))", re.I),
    },
]


def scan(text: str) -> list[dict]:
    """Return fired flags with the matched snippet. Context, never a score."""
    hits = []
    for f in FLAGS:
        m = f["re"].search(text)
        if m:
            snippet = m.group(0).strip()
            hits.append({
                "id": f["id"],
                "label": {"en": f["en"][0], "hi": f["hi"][0]},
                "why": {"en": f["en"][1], "hi": f["hi"][1]},
                "matched": snippet[:80],
            })
    return hits


# --- self-check --------------------------------------------------------------
if __name__ == "__main__":
    scam = ("Join our VIP tips group on Telegram! SEBI registered advisor. "
            "Guaranteed 30% monthly return, double your money! Act fast, last chance today. "
            "Withdrawal blocked? Pay unlock fee / tax deposit karo to release your money. "
            "Transfer to my personal account 9876543210. Kisi ko mat batana. "
            "Download the app APK link. Profit screenshot bhej raha hoon. "
            "राकेश झुनझुनवाला जैसे निवेशक भी इस ग्रुप में हैं। निकासी ब्लॉक है, फीस जमा करो।")
    ids = {h["id"] for h in scan(scam)}
    for want in ["guaranteed_returns", "urgency", "unlock_fees", "personal_account",
                 "tips_group", "celebrity_bait", "secrecy", "sideload_app",
                 "sebi_claim", "fake_profit_proof"]:
        assert want in ids, f"missing {want} in {ids}"
    benign = ("Zerodha Broking Limited is a registered stock broker. You can open a "
              "demat account through their official app. Mutual fund investments are "
              "subject to market risks; past performance does not guarantee future returns.")
    benign_hits = scan(benign)
    assert not any(h["id"] in {"unlock_fees", "personal_account", "tips_group", "secrecy"}
                   for h in benign_hits), benign_hits
    print(f"redflags.py self-check OK: {len(ids)} categories fired on scam text; "
          f"benign text fired {[h['id'] for h in benign_hits] or 'nothing'}")

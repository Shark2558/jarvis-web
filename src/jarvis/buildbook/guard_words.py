# src/jarvis/buildbook/guard_words.py
"""The talk-through guard's word lists and patterns (R6 D12), and the one normal form untrusted
text is compared in (`normalise`: NFKC, invisible and zero-width characters out, Cyrillic, Greek,
small-capital and Armenian look-alikes folded to Latin, case folded, in-word separators and
spaced-out letters joined). Data only; `guard.py` decides. English, Hindi and Malayalam; the
Indic lists are normalised exactly like the text they are matched against.
"""

from __future__ import annotations

import re
import unicodedata

# (look-alike, Latin) pairs: Cyrillic, Greek, Latin small capitals, Armenian (after casefold)
PAIRS = (
    "аa вb сc дd еe һh іi јj кk ӏl мm нh оo рp ԛq ѕs тt уy ԝw хx үy ɡg αa βb εe ηn ιi κk μu νv οo"
    " ρp τt υu χx γy ωw ϲc ɑa ıi ℓl ᴀa ʙb ᴄc ᴅd ᴇe ғf ɢg ʜh ɪi ᴊj ᴋk ʟl ᴍm ɴn ᴏo ᴘp ʀr ᴛt ᴜu ᴠv"
    " ᴡw ʏy ᴢz օo սu ցg"
)

LOOKALIKE = str.maketrans({p[0]: p[1] for p in PAIRS.split()})

LEET = str.maketrans("013457@$!|", "oieastasil")

EXTRA_INVISIBLE = frozenset("\u034f\u115f\u1160\u17b4\u17b5\u3164\uffa0") | frozenset(
    chr(c) for c in (*range(0xFE00, 0xFE10), *range(0x180B, 0x180E))
)

IN_WORD = re.compile(r"(?<=\w)[\-\u2010-\u2015_.·'’`*](?=\w)")

SPACED = re.compile(r"(?<!\w)(?:\w[\s.\-_*/|,+]+){2,}\w(?!\w)")

SPACED_SEP = re.compile(r"[\s.\-_*/|,+]+")


def visible(text: str) -> str:
    return "".join(c for c in text if unicodedata.category(c) != "Cf" and c not in EXTRA_INVISIBLE)


def normalise(text: str) -> str:
    """One comparable form of untrusted text (the guard's 'as written' view)."""
    s = visible(unicodedata.normalize("NFKC", text)).casefold().translate(LOOKALIKE)
    s = IN_WORD.sub("", s)
    s = SPACED.sub(lambda m: SPACED_SEP.sub("", m.group()), s)
    return " ".join(s.split())


def words(*alts: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(alts) + r")\b")


def indic(*words: str) -> tuple[str, ...]:
    return tuple(normalise(w) for w in words)


# ---- injection / meta ----------------------------------------------------------------------------
META = words(
    r"(?:ignore|disregard|forget|override|bypass|skip)\b.{0,40}\b(?:instructions?|rules|prompts?"
    r"|guidelines|directions|guardrails|restrictions|polic(?:y|ies)|context|above)",
    r"system (?:prompt|message)",
    r"(?:hidden|initial|original|developer|secret) (?:prompt|message|instructions?)",
    r"(?:your|the) (?:prompt|instructions|rules|guidelines)",
    r"new instructions?",
    r"you are now",
    r"from now on",
    r"act as",
    r"pretend",
    r"role ?play",
    r"jailbreak",
    r"dan",
    r"do anything now",
    r"(?:developer|dev|god|admin|debug|maintenance|owner|unrestricted) mode",
    r"sudo",
    r"repeat (?:the |all |everything |your |after )?(?:text|words|everything|instructions|prompt"
    r"|above|before|me|this)",
    r"(?:print|show|give|send|reveal|dump|output|display|paste) (?:me )?(?:the |your )?"
    r"(?:source )?code",
    r"source code",
    r"(?:print|output|reveal|dump|show) (?:me )?your",
    r"what (?:are|were) your (?:instructions|rules)",
    r"base ?64|rot ?13|hex ?encoded",
    r"book reference",
    r"reference marker|canary",
    r"(?:i am|im|i m|this is|as) (?:the |your )?(?:owner|creator|master|boss|admin)",
    r"main (?:hi )?maa?lik (?:hoon|hu|hun)",
)

META_SQUEEZED = (
    "ignorepreviousinstructions",
    "ignoreallinstructions",
    "systemprompt",
    "developermode",
    "youarenow",
    "repeatthetextabove",
)

META_INDIC = indic("मैं मालिक", "मैं ही मालिक", "ഞാൻ ഉടമ", "ഞാനാണ് ഉടമ")

META_INDIC_PAIRS = (
    (indic("निर्देश"), indic("भूल", "अनदेखा", "नज़रअंदाज़", "नजरअंदाज")),
    (indic("നിർദ്ദേശ", "നിർദേശ"), indic("അവഗണി", "മറക്ക", "മറന്ന")),
)

BLOB = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}|\b[0-9a-fA-F]{32,}\b")

# ---- hard data signals ---------------------------------------------------------------------------
DIGITS = re.compile(r"\+?\d(?:[\s\-.()]{0,2}\d){9,}")

# ---- actions -------------------------------------------------------------------------------------
VERB = (
    r"(?:send|email|mail|text|message|sms|whatsapp|call|ring|dial|phone|delete|remove|erase|wipe"
    r"|destroy|purge|buy|order|purchase|pay|transfer|reserve|switch|turn|arm|disarm|unlock|lock"
    r"|open|close|start|stop|run|execute|launch|install|deploy|push|upload|post|publish|forward"
    r"|reply|schedule|cancel|approve|reject|accept|set|remind|add|create|invite|share|download"
    r"|reset|change|update|edit|rename|move|play|pause|record|take|capture|enable|disable"
    r"|activate|deactivate|connect|disconnect)"
)

FILLER = r"(?:(?:please|pls|kindly|jarvis|hey|hi|ok|okay|now|just|quickly|so|and|then|go ahead and)[,!\s]+)*"  # noqa: E501

ACTION = re.compile(
    rf"^{FILLER}(?:(?:can|could|would|will|wont|won ?t) you (?:please |just )?)?{VERB}\b"
    rf"|\bi (?:want|need|would like|d like) you to {VERB}\b"
    rf"|\byou (?:must|should|need to|have to|will) {VERB}\b"
    rf"|\b(?:lets|let us) {VERB}\b|\bgo (?:and )?{VERB}\b|\bplease {VERB}\b"
    r"|\b(?:bhejo|bhej do|mitao|hatao|kharido|(?:on|band|call|delete) karo)\b"
)

ACTION_INDIC = indic(
    "भेजो",
    "भेज दो",
    "भेजें",
    "मिटाओ",
    "मिटा दो",
    "हटाओ",
    "डिलीट कर",
    "खरीदो",
    "खरीद लो",
    "चालू करो",
    "ऑन करो",
    "बंद करो",
    "कॉल करो",
    "फोन करो",
    "फ़ोन करो",
    "खोलो",
    "അയയ്ക്കൂ",
    "അയക്കൂ",
    "അയക്ക്",
    "ഡിലീറ്റ് ചെയ്യ",
    "മായ്ക്കൂ",
    "വാങ്ങൂ",
    "ഓൺ ചെയ്യ",
    "ഓഫ് ചെയ്യ",
    "വിളിക്കൂ",
    "തുറക്കൂ",
)

SENTENCE = re.compile(r"[.!?;:\n]+\s*")

# ---- the owner's data ----------------------------------------------------------------------------
STRONG = (
    r"(?:email|mail|gmail) (?:address(?:es)?|ids?)|emailaddress|(?:phone|mobile|cell|contact"
    r"|account|card|aadhaa?r|pan|passport) numbers?|(?:home|house|postal) address(?:es)?"
    r"|pass(?:words?|codes?)|pins?|pin code|otps?|one time password|(?:api|secret|private) keys?"
    r"|access tokens?|credentials|bank accounts?|credit cards?|debit cards?|cvv|(?:bank )?balance"
    r"|salary|aadhaa?r|pan card|upi(?: id)?|ifsc|date of birth|birthday"
)

CONTENT = (
    r"e?mails?|gmail|inbox|messages?|chats?|conversations?|history|calendars?|schedule|meetings?"
    r"|appointments?|events?|contacts?|phone|mobile|numbers?|address(?:es)?|location|whereabouts"
    r"|family|wife|husband|kids?|children|child|sons?|daughters?|mother|father|mom|dad|parents?"
    r"|brother|sister|friends?|girlfriend|boyfriend|partner|money|bank|accounts?|spend(?:ing)?"
    r"|expenses?|budget|income|cards?|vault|documents?|files?|photos?|pictures?|cameras?|faces?"
    r"|health|vitals|weight|memory|memories|remember|notes|keys?|secrets?|tokens?|pata|ghar"
)

TOPIC = re.compile(rf"\b(?:{STRONG}|{CONTENT})\b")

STRONG_RE = re.compile(rf"\b(?:{STRONG})\b")

PERSON = words(
    r"owners?",
    "his",
    "him",
    "her",
    "hers",
    "he",
    "she",
    "their",
    "my",
    "mine",
    "boss",
    "master",
    "maa?lik",
    "unk[aie]",
    "us(?:ka|ki|ke)",
    "mer[aie]",
    "udama\\w*",
)

# about a person only (with an owner / his / her word): "his name", "how old is your owner"
PERSON_ONLY = words(
    r"names?",
    "age",
    "old",
    "birthday",
    "born",
    "religion",
    "caste",
    "job",
    "company",
    "employer",
    "office",
    "workplace",
    "school",
    "college",
    "nationality",
    r"lives?",
    "living",
)

YOURS = re.compile(rf"\byour (?:\w+ ){{0,2}}?(?:{STRONG}|{CONTENT})\b")

REQUEST = words(
    r"what|whats|which|who|whom|whose|where|when|tell|give|show|share|send|read|list|reveal",
    r"print|dump|display|spell|say|provide|need|want|know|get|fetch|find|look ?up|disclose|leak",
    r"expose|recite|kya",
)

REVEAL = words(
    r"what(?: i|)s in(?:side)?|what (?:is|are) in(?:side)?|anything (?:in|on)|read (?:me|out|aloud"
    r"|the)|show (?:me|the)|list|who(?: i|)s (?:in|on)|who (?:is|are) (?:in|on)|summari[sz]e"
    r"|open|dump|print|recite|give me|send me|share|forward|export|download|copy",
)

FEATURE = re.compile(
    r"^(?:(?:so|and|but|ok|okay|jarvis|hey|please|then)[,\s]+)*(?:how|why|explain|describe"
    r"|in what way|what happens)\b|\bhow (?:does|do|is|are|would|can|will|did|could|much)\b"
)

WHERE = re.compile(
    r"\bwhere(?:abouts)?\b.{0,12}\b(?:he|she|him|her|owners?|they)\b"
    r"|\bwhere (?:does|do|is|did) (?:your |the )?owner"
)

PERSON_INDIC = indic(
    "मालिक",
    "स्वामी",
    "उनका",
    "उनकी",
    "उनके",
    "उसका",
    "उसकी",
    "उसके",
    "मेरा",
    "मेरी",
    "मेरे",
    "ഉടമ",
    "അദ്ദേഹത്തിന്റെ",
    "അവന്റെ",
    "അവളുടെ",
    "എന്റെ",
)

TOPIC_INDIC = indic(
    "ईमेल",
    "ई-मेल",
    "मेल",
    "फ़ोन",
    "फोन",
    "नंबर",
    "नम्बर",
    "पता",
    "पासवर्ड",
    "परिवार",
    "पत्नी",
    "पति",
    "बच्चे",
    "बैंक",
    "खाता",
    "पैसा",
    "पैसे",
    "कैलेंडर",
    "संपर्क",
    "घर",
    "ഇമെയിൽ",
    "മെയിൽ",
    "ഫോൺ",
    "നമ്പർ",
    "വിലാസം",
    "പാസ്\u200cവേഡ്",
    "കുടുംബം",
    "ഭാര്യ",
    "ഭർത്താവ്",
    "ബാങ്ക്",
    "അക്കൗണ്ട്",
    "പണം",
    "കലണ്ടർ",
    "വീട്",
)

# ---- the reply -----------------------------------------------------------------------------------
EMAIL = re.compile(
    r"[\w.+\-]+\s*(?:@|\(at\)|\[at\]|\{at\})\s*[\w\-]+(?:\s*(?:\.|\(dot\)|\[dot\]|\{dot\})\s*"
    r"[\w\-]+)+"
)

SECRETS = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AIza[0-9A-Za-z_\-]{35}|sk-ant-[A-Za-z0-9_\-]{10,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|\bAKIA[0-9A-Z]{16}\b"
    r"|\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"
)

URL = re.compile(r"\bhttps?://[^\s<>\"'()\[\]{}]+|\bwww\.[^\s<>\"'()\[\]{}]+", re.IGNORECASE)

TLDS = r"com|org|net|io|in|co|ai|dev|me|info|xyz|gov|edu|uk|us|biz|site|online|link|ly|to|run\.app"

DOMAIN = re.compile(
    rf"(?<![\w@./\-])(?:[a-z0-9](?:[a-z0-9\-]{{0,61}}[a-z0-9])?\.)+(?:{TLDS})"
    rf"(?![\w\-])"
)

CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

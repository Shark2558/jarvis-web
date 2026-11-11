# src/jarvis/helpers/kitchen/diet_words.py
"""The diet check's word lists (docs/plans/r11-free-helpers.md D15; security review H1, M1).

Latin stems are matched on a normalised copy of the text (`diet.latin_form`):
- `*_ANYWHERE`: anywhere inside a word ("chicken65", "crabmeat", "meatballs"), and the ones of 5 or
  more letters also on a copy with every space and sign removed ("Chic ken", "c.h.i.c.k.e.n").
- `*_WORD_START`: only at the start of a word ("hamburger", "tuna steak"), because they sit inside
  ordinary cooking words: ham (khaman), veal (reveal), tuna (fortunate), lard (collard), liver
  (slivered), paya (papaya), anda (kanda poha), ande (coriander), eral (several), salami (masala
  mix), pepperoni (pepper, onion), venison (the oven is on), ilish (chili, shredded), nalli (final
  lime), mathi (from a thick), aanda (soda and a), irachi / erachi (stir a chilli, over a chickpea).
- `HARMLESS` are vegetarian words that hold a stem; each is blanked before the stems are looked for.
Words in Indian scripts (`*_NATIVE`) match anywhere, also with spaces removed. When in doubt a word
is on the list: a vegetable dish wrongly refused costs one more try, meat in a veg kitchen never.

`STAPLES` are what a new idea may use besides his pantry (salt, water, oils, ghee, sugar and the
common spices), and `QUALIFIERS` the cooking words dropped before an ingredient is compared.
"""

from __future__ import annotations

MEAT_ANYWHERE = (
    # English: meat, poultry, offal, animal fats and setting agents
    "chicken", "mutton", "lamb", "beef", "pork", "bacon", "sausage", "turkey", "duck", "quail",
    "meat", "goat", "kidney", "brain", "tripe", "trotter", "offal", "mince", "gelatin", "rennet",
    "tallow", "suet", "isinglass", "bone broth", "rabbit", "pheasant", "partridge", "jerky",
    "pastrami", "prosciutto", "pancetta", "chorizo", "bresaola", "foie", "kebab", "kabab",
    # fish and seafood
    "fish", "salmon", "sardine", "mackerel", "pomfret", "hilsa", "rohu", "katla", "surmai",
    "anchov", "tilapia", "bhetki", "bekti", "shrimp", "prawn", "lobster", "crab", "squid",
    "calamari", "octopus", "oyster", "mussel", "clam", "scallop", "caviar", "sushi", "sashimi",
    "surimi", "bonito", "seafood", "worcestershire",
    # Hindi / Urdu in Latin letters
    "murg", "gosht", "keema", "kheema", "qeema", "machh", "machl", "macch", "maach", "jhinga",
    "jheenga", "kaleji", "bakra", "nihari", "haleem",
    # Malayalam, Odia, Bengali and Tamil in Latin letters
    "kozhi", "meen", "njandu", "kakka", "pothu", "kallummakkaya", "koonthal", "ayila", "nethili",
    "chingudi", "kankada", "mansa", "mangsa", "mangsho", "kukuda", "chingri", "nandu", "bangda",
    "bombil",
)  # fmt: skip
MEAT_WORD_START = (
    "ham", "veal", "venison", "steak", "liver", "lard", "hog", "salami", "pepperoni", "pate",
    "cod", "tuna", "eel", "roe", "carp", "basa", "dashi", "ilish", "paya", "nalli", "mathi",
    "ayala", "eral", "irachi", "erachi",
)  # fmt: skip
EGG_ANYWHERE = (
    "egg", "omelet", "omlet", "frittata", "quiche", "meringue", "mayo", "albumen", "albumin",
    "yolk", "mutta",
)  # fmt: skip
EGG_WORD_START = ("anda", "ande", "aanda")
MEAT_NATIVE = (
    "चिकन", "मुर्ग", "मछली", "गोश्त", "मांस", "झींगा", "कीमा", "मटन", "फिश", "मीट", "बीफ",
    "കോഴി", "മീൻ", "ചെമ്മീൻ", "ഇറച്ചി", "ബീഫ്", "ഞണ്ട്", "ചിക്കൻ", "മട്ടൻ", "മത്സ്യ",
    "ମାଛ", "ଚିଙ୍ଗୁଡ଼ି", "ମାଂସ", "କୁକୁଡ଼ା",
    "கோழி", "மீன்", "இறால்", "இறைச்சி", "சிக்கன்", "மட்டன்", "நண்டு",
    "মাছ", "মাংস", "চিংড়ি", "চিকেন", "ইলিশ",
)  # fmt: skip
EGG_NATIVE = ("अंडा", "अंडे", "एग", "മുട്ട", "ଅଣ୍ଡା", "முட்டை", "ডিম")
HARMLESS = (
    r"\beggs?\s*plants?\b", r"\beggless\b", r"\beggs?[\s-]*free\b", r"\bveggies?\b",
    r"\bchick\s*peas?\b", r"\bkidney\s+beans?\b", r"\bcoconut\s+meat\b",
    r"\bmeat(?:less|[\s-]*free)\b", r"\boyster\s+mushrooms?\b", r"\bscalloped\b", r"\bmuttar\b",
    r"\bkozhikode\b", r"\bminced\b", r"\bmacchiatos?\b",
)  # fmt: skip

# Look-alike letters (after casefold) that stand in for Latin ones.
CONFUSABLES = {
    # Cyrillic
    "а": "a", "в": "b", "г": "r", "е": "e", "ё": "e", "з": "3", "и": "u", "й": "u", "к": "k",
    "м": "m", "н": "h", "о": "o", "п": "n", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x",
    "ь": "b", "ѕ": "s", "і": "i", "ї": "i", "ј": "j", "ԁ": "d", "һ": "h", "ӏ": "l", "ԛ": "q",
    "ԝ": "w", "ш": "w",
    # Greek
    "α": "a", "β": "b", "γ": "y", "δ": "d", "ε": "e", "η": "n", "ι": "i", "κ": "k", "μ": "u",
    "ν": "v", "ο": "o", "π": "n", "ρ": "p", "σ": "o", "ς": "c", "τ": "t", "υ": "u", "χ": "x",
    "ω": "w",
    # Latin letters with no decomposition
    "ı": "i", "ȷ": "j", "ł": "l", "ø": "o", "đ": "d", "ħ": "h", "ɡ": "g", "ɩ": "i", "ʋ": "u",
}  # fmt: skip
# Malayalam chillu letters written the old way (a virama and a ZWJ), as their atomic letters.
CHILLU = {"ണ്‍": "ൺ", "ന്‍": "ൻ", "ര്‍": "ർ", "ല്‍": "ൽ", "ള്‍": "ൾ"}

STAPLES = (
    "salt", "black salt", "rock salt", "water", "oil", "cooking oil", "vegetable oil",
    "refined oil", "sunflower oil", "groundnut oil", "peanut oil", "coconut oil", "mustard oil",
    "sesame oil", "gingelly oil", "olive oil", "ghee", "sugar", "turmeric", "turmeric powder",
    "haldi", "red chilli powder", "red chili powder", "kashmiri chilli powder", "chilli powder",
    "chili powder", "dried red chilli", "dry red chilli", "red chilli", "cumin", "cumin seed",
    "cumin powder", "jeera", "mustard seed", "coriander powder", "dhania powder", "garam masala",
    "black pepper", "pepper", "pepper powder", "asafoetida", "hing", "curry leaf", "curry leave",
    "bay leaf", "cardamom", "green cardamom", "clove", "cinnamon", "fennel seed", "fenugreek seed",
    "methi seed", "kasuri methi", "ajwain", "carom seed", "nigella seed", "kalonji", "amchur",
    "chaat masala", "sambar powder", "rasam powder",
)  # fmt: skip
STAPLE_WORDS = "salt, water, oil, ghee, sugar and the common spices (" + ", ".join(
    ("turmeric", "chilli powder", "cumin", "mustard seeds", "coriander powder", "garam masala",
     "pepper", "hing", "curry leaves", "bay leaf", "cardamom", "cloves", "cinnamon", "fennel",
     "fenugreek", "ajwain")
) + ")"  # fmt: skip
QUALIFIERS = frozenset(
    "a an of some few little pinch handful fresh freshly chopped finely roughly sliced thinly "
    "diced cubed grated minced crushed ground whole dry dried raw ripe boiled cooked soaked "
    "peeled small medium large big optional to taste for garnish garnishing leaf leave leaves "
    "sprig".split()
)

__all__ = [
    "CHILLU",
    "CONFUSABLES",
    "EGG_ANYWHERE",
    "EGG_NATIVE",
    "EGG_WORD_START",
    "HARMLESS",
    "MEAT_ANYWHERE",
    "MEAT_NATIVE",
    "MEAT_WORD_START",
    "QUALIFIERS",
    "STAPLES",
    "STAPLE_WORDS",
]

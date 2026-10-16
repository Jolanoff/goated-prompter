"""Local, deterministic text matching for vocabulary retrieval (Phase 4).

No model, service or download: meaning comes from the vocabulary's own words (names, aliases,
tags, descriptions, notes) and from the links between entries, which retrieval.py adds on top.
This module only knows English morphology in general (plural and verb endings, a short list of
function words), never any content domain.

    tokens("Two people kneeling, no toys")  -> ["two", "people", "kneeling", "no", "toys"]
    stem("kneeling") == stem("kneels") == "kneel"
    split_negated(...)                       -> positive terms, and the terms after no/not/without
"""

from dataclasses import dataclass, field
from functools import lru_cache
import math
import re

_WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset("""
a an the and or but if then than so as of at by for from in into onto on off out to with within
without about before after again further once is are was were be been being am do does did
doing have has had having i me my we our you your he him his she her it its they them their this that these those who
whom which what when where why how all any both each few more most other some such only own same very can will just
should would could may might must shall let lets also each every per via
""".split())
NEGATIONS = frozenset({"no", "not", "without", "never", "avoid", "except", "nor", "none"})
# Function words that carry a phrase's structure (prepositions and conjunctions). A name or alias is matched only where
# the request has the same structure: it never skips one it does not contain ("a book in the corner" is not "Book
# corner"), while articles, pronouns and possessives may sit between its words ("sitting on her lap"). A closed
# grammatical class, never a list of subjects.
STRUCTURAL = frozenset("at by for from in into onto on off out to with within about of and or but".split())
_CLAUSE_END = frozenset({"and", "but", "while", "with", "then"})
_ALTERNATIVE = frozenset({"or"})
_DOUBLE_KEEP = set("lsz")


def tokens(text):
    return _WORD.findall(str(text or "").casefold().replace("'s ", " ").replace("'", ""))


def grounded(text, sources):
    """Whether an annotation's positive wording is supported by authoritative source texts."""
    positive = {word for source in sources for word in split_negated(source)[0]}
    words, negative = split_negated(text)
    return bool(words) and set(words) <= positive and not negative


@lru_cache(maxsize=65536)
def stem(word):
    """A light, deterministic suffix stripper: plurals, -ing, -ed, -ly and a final e."""
    w = word
    if len(w) <= 3 or w.isdigit():
        return w
    if w.endswith("ying") and len(w) == 5:
        return w[0] + "ie"  # lying, dying, tying -> lie, die, tie
    if w.endswith(("ies", "ied")) and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("ied"):
        w = w[:-1]  # tied, died -> tie, die
    elif w.endswith("sses"):
        w = w[:-2]
    elif w.endswith(("ches", "shes", "xes", "zes", "sses")):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suffix in ("ingly", "edly", "ing", "ed"):
        if suffix == "ed" and w.endswith("eed"):
            break  # speed, bleed, steed: the "ed" is not an ending
        base = w[:-len(suffix)]
        if w.endswith(suffix) and len(base) == 2 and base[0] in "aeiou" and base[1] not in "aeiouy":
            w = base + "e"  # using -> use, aged -> age
            break
        if w.endswith(suffix) and len(base) >= 3 and any(vowel in base for vowel in "aeiouy"):
            w = base
            if len(w) > 3 and w[-1] == w[-2] and w[-1] not in _DOUBLE_KEEP and w[-1] not in "aeiou":
                w = w[:-1]
            break
    if w.endswith("ly") and len(w) > 5:
        w = w[:-2]
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


def terms(text):
    """Stemmed content terms in order (function words dropped)."""
    return [stem(word) for word in tokens(text) if word not in STOPWORDS and word not in NEGATIONS]


# Prepositions that can say where a scene is ("on a train platform", "in a dark forest").
LOCATIVES = frozenset("in on at inside outside under beneath near beside across through around atop onto into within "
                      "along above below over".split())


def place_phrases(text):
    """[(preposition, terms)]: each locative preposition with the first content words after it in its clause
    (at most two): "hugging on a train platform" -> [("on", ["train", "platform"])]. Whether a phrase names a
    place the vocabulary knows, a position or a category is for the caller to decide."""
    found = []
    for clause in re.split(r"[.,;:!?\n()]+", str(text or "")):
        words = tokens(clause)
        for index, word in enumerate(words):
            if word not in LOCATIVES or (index and words[index - 1] in NEGATIONS):
                continue
            following = []
            for other in words[index + 1:]:
                if other in LOCATIVES or other in _CLAUSE_END or other in NEGATIONS:
                    break
                if other not in STOPWORDS:
                    following.append(stem(other))
                    if len(following) == 2:
                        break
            if following:
                found.append((word, following))
    return found


def marker(word):
    """How a structural word stands in a phrase: "@", the same for every one, so a name keeps its shape but not its
    exact preposition ("sitting in a lap" holds "Sitting on a lap"). Markers are never terms: they keep words apart."""
    return "@"


def phrase_terms(text):
    """The terms of a name, alias, tag or theme with its inner structural words kept as markers:
    "Sitting on a lap" -> ["sit", "@", "lap"]; leading and trailing ones are dropped ("On top" -> ["top"])."""
    out = [marker(word) if word in STRUCTURAL else stem(word) for word in tokens(text) if word not in STOPWORDS or word in STRUCTURAL]
    while out and out[0].startswith("@"):
        out.pop(0)
    while out and out[-1].startswith("@"):
        out.pop()
    return out


def split_negated(text, structure=False):
    """(positive terms, negated terms). A negation word rules out the next content words of its clause.
    structure: keep the structural words of the positive terms as markers ("@"), for phrase matching.

    The scope also ends at a new verb form (-ing, -ed) unless that verb is itself what is negated, directly
    after the negation or after "or": "no shirt, cuddling" and "no shirt cuddling" both keep "cuddling",
    while "no kneeling" and "no toys or kneeling" rule kneeling out.
    """
    positive, negated = [], []
    for clause in re.split(r"[.,;:!?\n()]+", str(text or "")):
        words, remaining, fresh = tokens(clause), 0, False
        for word in words:
            if word in NEGATIONS:
                remaining, fresh = 3, True
                continue
            if word in _CLAUSE_END:
                remaining = 0
            if word in _ALTERNATIVE:
                fresh = True
            if word in STOPWORDS:
                if structure and word in STRUCTURAL and not remaining:
                    positive.append(marker(word))
                continue
            term = stem(word)
            if remaining and not fresh and word.endswith(("ing", "ed")) and term != word:
                remaining = 0
            (negated if remaining else positive).append(term)
            remaining, fresh = max(0, remaining - 1), False
    return positive, negated


def trigrams(term):
    padded = f"#{term}#"
    return frozenset(padded[index:index + 3] for index in range(len(padded) - 2))


def similarity(a, b):
    """Character-trigram Jaccard similarity of two terms (spelling and word-form variants)."""
    if a == b:
        return 1.0
    first, second = trigrams(a), trigrams(b)
    return len(first & second) / len(first | second)


@dataclass
class Document:
    """One entry's searchable text: weighted term frequencies per field, and its phrases."""
    key: str
    fields: dict                                   # {field: [terms]}
    phrases: list = field(default_factory=list)    # [(label, field, (terms...))]


class TextIndex:
    """BM25 over weighted fields, with fuzzy term expansion and phrase detection."""

    K1, B = 1.2, 0.5
    FUZZY_MIN = 0.55       # trigram similarity for a variant to count
    FUZZY_WEIGHT = 0.6     # a variant counts this much of an exact term
    PREFIX_WEIGHT = 0.5    # a compound that starts with the term ("spell" in "spellcaster")

    def __init__(self, documents, weights, corpus=None, members=None):
        """corpus: {key: corpus id} and members: {corpus id: [keys]}: the documents whose statistics (term rarity,
        average length) score a key. A key is scored against its own corpus only, so documents outside it never
        change its score. Without them every document shares one corpus."""
        self.weights = dict(weights)
        self.documents = {document.key: document for document in documents}
        self.tf, self.length = {}, {}
        frequency = {}
        for key in sorted(self.documents):
            document = self.documents[key]
            bag = {}
            for name in sorted(document.fields):
                for term in document.fields[name]:
                    bag.setdefault(term, {}).setdefault(name, 0)
                    bag[term][name] += 1
            self.tf[key] = bag
            self.length[key] = sum(self.weights.get(name, 0) * len(items) for name, items in document.fields.items())
            for term in bag:
                frequency[term] = frequency.get(term, 0) + 1
        count = max(1, len(self.documents))
        self.idf = {term: math.log(1 + (count - df + .5) / (df + .5)) for term, df in frequency.items()}
        self.average = (sum(self.length.values()) / count) or 1.0
        self.vocabulary = sorted(self.idf)
        # Statistics per corpus: {corpus id: (idf, average length)}; a key without a corpus uses the global ones.
        self.corpus = dict(corpus or {})
        self._stats = {group: self._statistics(keys) for group, keys in sorted((members or {}).items(), key=lambda item: repr(item[0]))}
        self._grams = {}
        for term in self.vocabulary:
            for gram in trigrams(term):
                self._grams.setdefault(gram, []).append(term)
        self._variants = {}

    def _statistics(self, keys):
        keys = [key for key in keys if key in self.documents]
        frequency = {}
        for key in keys:
            for term in self.tf[key]:
                frequency[term] = frequency.get(term, 0) + 1
        count = max(1, len(keys))
        idf = {term: math.log(1 + (count - df + .5) / (df + .5)) for term, df in frequency.items()}
        return idf, (sum(self.length[key] for key in keys) / count) or 1.0

    def stats(self, key):
        """(idf, average length) that score this key."""
        return self._stats.get(self.corpus.get(key), (self.idf, self.average))

    def variants(self, term):
        """Indexed terms that match term: itself, plus close spelling variants (sorted, deterministic)."""
        if term in self._variants:
            return self._variants[term]
        found = {term: 1.0} if term in self.idf else {}
        if len(term) >= 4:
            candidates = sorted({other for gram in trigrams(term) for other in self._grams.get(gram, ())})
            for other in candidates:
                if other != term and len(other) >= 4:
                    score = similarity(term, other)
                    if score >= self.FUZZY_MIN:
                        found[other] = max(found.get(other, 0), self.FUZZY_WEIGHT * score)
                    if other.startswith(term):  # the vocabulary's compound contains the query word
                        found[other] = max(found.get(other, 0), self.PREFIX_WEIGHT)
        self._variants[term] = sorted(found.items())
        return self._variants[term]

    def score(self, key, query, exact=False):
        """Score one document for {term: (weight, source)}; returns (score, [(term, matched, field, source, value)]).

        exact: the same normalized word only, no spelling variants or compounds ("hand" never matches "handbag").
        """
        bag, total, matches = self.tf.get(key, {}), 0.0, []
        idf, average = self.stats(key)
        norm = 1 - self.B + self.B * self.length.get(key, 0) / average
        for term in sorted(query):
            weight, source = query[term]
            best = None
            for other, closeness in ([(term, 1.0)] if exact else self.variants(term)):
                fields = bag.get(other)
                if not fields:
                    continue
                tf = sum(self.weights.get(name, 0) * count for name, count in fields.items())
                value = weight * closeness * idf.get(other, 0.0) * tf * (self.K1 + 1) / (tf + self.K1 * norm)
                strongest = max(sorted(fields), key=lambda name: self.weights.get(name, 0))
                if best is None or value > best[4]:
                    best = (term, other, strongest, source, value)
            if best:
                total += best[4]
                matches.append(best)
        return total, matches

    def phrase_hits(self, key, sequences):
        """Multi-word names and aliases found in the query. sequences: [(source, weight, [terms])]."""
        hits, idf = [], self.stats(key)[0]
        for label, name, phrase in self.documents[key].phrases:
            if len(phrase) < 2:
                continue
            for source, weight, sequence in sequences:
                contiguous = any(tuple(sequence[index:index + len(phrase)]) == phrase for index in range(len(sequence) - len(phrase) + 1))
                present = set(phrase) <= set(sequence)
                if contiguous or present:
                    value = weight * (1.0 if contiguous else .5) * sum(idf.get(term, 0) for term in phrase)
                    hits.append((label, name, source, value, contiguous))
        hits.sort(key=lambda hit: (-hit[3], hit[0], hit[2]))
        return hits

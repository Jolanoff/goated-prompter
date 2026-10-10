"""User prompt library: one untracked text file per target, searched locally.

Each target has a plain-text file under data/prompt_library/ (or the
GOATED_PROMPTER_LIBRARY_DIR override). Prompts are separated by a line that is
exactly ``---``; lines starting with ``#`` are comments. Files are created on
first app launch, re-read only when they change, and searched with BM25, so even
very large libraries cost milliseconds per request and no model call.
"""

from collections import Counter
import math
import os
from pathlib import Path
import random
import re
import threading

from .config import PROJECT_ROOT
from .options.targets import TARGET_MODEL_NAMES, canonical_target
from .output_repetition import anima_tags

LIBRARY_DIR_ENV = "GOATED_PROMPTER_LIBRARY_DIR"
SEPARATOR = "---"
HEADER = """# Goated Prompter prompt library for {target}
#
# Paste prompts you like for this target model. Separate prompts with a line
# that contains only three dashes:
#
# ---
#
# Lines starting with # are ignored. Blank lines inside a prompt are kept, so
# Anima "tags, blank line, prose" prompts work as they are.
# When your idea or scene matches a prompt here, the app uses it as a reference
# for the final prompt. This file is yours: it is never tracked or overwritten.
"""
_STOPWORDS = frozenset("a an the and or of in on at to with for from by is are was were be her his their its "
                       "she he they it this that as into over under while".split())
_K1, _B = 1.5, 0.75
_lock = threading.Lock()
_cache = {}


def library_directory():
    configured = os.environ.get(LIBRARY_DIR_ENV, "").strip()
    return Path(configured).expanduser() if configured else PROJECT_ROOT / "data" / "prompt_library"


def library_file_name(target):
    return re.sub(r"[^a-z0-9]+", "-", str(canonical_target(target)).casefold()).strip("-") + ".txt"


def library_path(target, directory=None):
    return Path(directory or library_directory()) / library_file_name(target)


def ensure_library_files(directory=None):
    """Create a commented, empty library file for every target that has none."""
    directory = Path(directory or library_directory())
    directory.mkdir(parents=True, exist_ok=True)
    for target in TARGET_MODEL_NAMES:
        path = directory / library_file_name(target)
        if not path.exists():
            path.write_text(HEADER.format(target=target), encoding="utf-8")


def parse_library(text):
    """Split library text into prompts, dropping comments and empty blocks."""
    prompts, block = [], []
    for line in str(text or "").splitlines():
        if line.strip() == SEPARATOR:
            prompts.append("\n".join(block).strip())
            block = []
        elif not line.lstrip().startswith("#"):
            block.append(line.rstrip())
    prompts.append("\n".join(block).strip())
    return tuple(prompt for prompt in prompts if prompt)


def tokenize(text):
    """Words for search: count tags split ("1girl" -> "girl"), simple plurals folded, stopwords dropped."""
    value = str(text or "").casefold().replace("\\", "").replace("_", " ")
    tokens = []
    for token in re.findall(r"[a-z]+", value):
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        if token not in _STOPWORDS:
            tokens.append(token)
    return tokens


class LibraryIndex:
    """BM25 index and style profile for one target's prompts."""

    def __init__(self, prompts):
        self.prompts = tuple(prompts)
        self.profile = style_profile(self.prompts)
        self.terms = [Counter(tokenize(prompt)) for prompt in self.prompts]
        self.lengths = [sum(terms.values()) for terms in self.terms]
        self.average = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0
        frequency = Counter(term for terms in self.terms for term in terms)
        total = len(self.prompts)
        self.idf = {term: math.log(1 + (total - count + .5) / (count + .5)) for term, count in frequency.items()}

    def search(self, query, limit=10):
        """Return (score, prompt) pairs with a positive score, best first."""
        wanted = set(tokenize(query))
        if not wanted or not self.prompts:
            return []
        scored = []
        for index, terms in enumerate(self.terms):
            score = 0.0
            for term in wanted & terms.keys():
                count = terms[term]
                norm = _K1 * (1 - _B + _B * self.lengths[index] / (self.average or 1))
                score += self.idf[term] * count * (_K1 + 1) / (count + norm)
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [(score, self.prompts[index]) for score, index in scored[:limit]]


_SECTION_LINE = re.compile(r"^\s*([A-Z][A-Za-z &/-]{2,40}):\s*(?:\S.*)?$")
# Each length picks a point in the library's own spread of prompt lengths, so Maximum Detail
# writes like the user's longest prompts and Short like their shortest, not a scaled median.
LENGTH_QUANTILE = {"Short": .25, "Medium": .5, "Detailed": .75, "Maximum Detail": .9, "Maximum": .9}


def _leading_tags(prompt):
    first = prompt.strip().splitlines()[0] if prompt.strip() else ""
    parts = [part.strip() for part in first.split(",") if part.strip()]
    return len(parts) >= 5 and sum(len(part.split()) for part in parts) / len(parts) <= 3


def style_profile(prompts):
    """Measure how the user's prompts are written: length, structure, section labels and a shared lead token."""
    if not prompts:
        return None
    lengths = sorted(len(prompt.split()) for prompt in prompts)
    sections = [[match[1] for line in prompt.splitlines() if (match := _SECTION_LINE.match(line))] for prompt in prompts]
    sectioned = [labels for labels in sections if len(labels) >= 2]
    tagged = sum(_leading_tags(prompt) for prompt in prompts)
    half = len(prompts) / 2
    structure = ("labeled sections" if len(sectioned) >= half else "a leading tag list, then prose" if tagged >= half
                 else "flowing prose paragraphs" if not sectioned and not tagged else "mixed: some sectioned, some prose")
    labels = Counter(label for found in sectioned for label in dict.fromkeys(found))
    order = list(dict.fromkeys(label for found in sectioned for label in found if labels[label] > len(sectioned) / 2))
    leads = Counter(prompt.strip().split(",")[0].strip() for prompt in prompts if "," in prompt.strip().splitlines()[0])
    lead, uses = leads.most_common(1)[0] if leads else ("", 0)
    return {"count": len(prompts), "median_words": lengths[len(lengths) // 2], "lengths": lengths, "structure": structure,
            "sections": order if len(sectioned) >= half else [],
            "lead": lead if uses >= 2 and uses >= half and len(lead.split()) <= 3 else ""}


def _quantile(values, fraction):
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def style_profile_text(profile, length):
    """Describe the library's style and the word target for the selected length."""
    lengths = profile.get("lengths") or [profile["median_words"]]
    words = max(25, round(_quantile(lengths, LENGTH_QUANTILE.get(length, .75)) / 5) * 5)
    spread = (f"from about {lengths[0]} to {lengths[-1]} words, typically {profile['median_words']}"
              if lengths[0] != lengths[-1] else f"about {lengths[0]} words")
    parts = [spread, f"written as {profile['structure']}"]
    if profile["sections"]:
        parts.append("with the sections " + ", ".join(f'"{label}:"' for label in profile["sections"]))
    if profile["lead"]:
        parts.append(f'starting with "{profile["lead"]}"')
    saved = f"{profile['count']} saved prompt" + ("" if profile["count"] == 1 else "s")
    return (f"YOUR LIBRARY'S STYLE ({saved}): " + "; ".join(parts) + ". "
            f"Write this prompt in that style at about {words} words for the selected {length} length.")


def load_library(target, directory=None):
    """Return the cached index for a target, re-reading the file only when it changes."""
    path = library_path(target, directory)
    try:
        stat = path.stat()
    except OSError:
        return LibraryIndex(())
    key = (stat.st_mtime_ns, stat.st_size)
    with _lock:
        cached = _cache.get(path)
        if cached is not None and cached[0] == key:
            return cached[1]
    try:
        prompts = parse_library(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        return LibraryIndex(())
    index = LibraryIndex(prompts)
    with _lock:
        _cache[path] = (key, index)
    return index


def pick_references(target, query, count=2, pool=10, rng=None, directory=None):
    """Pick ``count`` library prompts: random picks among the best matches, topped up with other saved prompts.

    References teach the user's style, so any saved prompt beats the built-in example;
    matching ones come first because they also fit the subject.
    """
    rng = rng or random
    index = load_library(target, directory)
    matches = [prompt for _score, prompt in index.search(query, pool)]
    picks = rng.sample(matches, count) if len(matches) > count else matches
    others = [prompt for prompt in index.prompts if prompt not in matches]
    picks += rng.sample(others, min(count - len(picks), len(others)))
    return tuple(picks)


def library_profile(target, directory=None):
    """The style profile of a target's library, or None when it is empty."""
    return load_library(target, directory).profile


def library_status(target, directory=None):
    path = library_path(target, directory)
    return {"target": canonical_target(target), "file": path.name, "path": str(path),
            "exists": path.exists(), "count": len(load_library(target, directory).prompts)}


_COUNT_TAG = re.compile(r"\(?(\d+)\s*(?:girl|boy|other)s?(?::\d+(?:\.\d+)?)?\)?")


def cast_size(prompt):
    """Count characters from Danbooru count tags (1girl, 2boys, ...); None when the prompt has none."""
    tags = [tag.strip().casefold().replace("_", " ") for tag in anima_tags(prompt)]
    counts = [int(match[1]) for tag in tags if (match := _COUNT_TAG.fullmatch(tag))]
    if counts:
        return sum(counts)
    return 1 if "solo" in tags else None


def _recast_recently(prompt, ideas, query):
    """True when a recent idea reads as a recast of this prompt: at least four of its own words
    (beyond the concept's) and over a third of them appear in the prompt; the rest are
    usually what the recast cast does."""
    words, shared = set(tokenize(prompt)), set(tokenize(query))
    for idea in ideas:
        own = set(tokenize(idea)) - shared
        shared_words = len(own & words)
        if shared_words >= 4 and shared_words / len(own) >= .35:
            return True
    return False


def pick_scenarios(target, query, count, cast=None, rng=None, directory=None, recent=()):
    """Choose ``count`` saved prompts to recast: best matches first (shuffled), then the rest.

    Prompts with fewer counted roles than the cast are used only when nothing else fits, and
    prompts that ``recent`` ideas already recast come after fresh ones, so generating again
    or regenerating one idea moves to other saved prompts while any are left.
    Prompts repeat only when the library holds fewer than ``count`` prompts.
    """
    rng = rng or random.Random()
    index = load_library(target, directory)
    if not index.prompts or count < 1:
        return ()
    matches = index.search(query, max(3 * count, 10))
    best = matches[0][0] if matches else 0
    # Shuffle within strong matches (at least half the best score) so runs vary without
    # trading a clear match for a weak one; weaker matches come next, then the rest.
    strong = [prompt for score, prompt in matches if score >= best / 2]
    weak = [prompt for score, prompt in matches if score < best / 2]
    rng.shuffle(strong)
    rng.shuffle(weak)
    ranked = strong + weak
    rest = [prompt for prompt in index.prompts if prompt not in set(ranked)]
    rng.shuffle(rest)
    fits = lambda prompt: cast is None or (size := cast_size(prompt)) is None or size >= cast
    stale = {prompt for prompt in index.prompts if _recast_recently(prompt, recent, query)}
    pool = ranked + rest
    ordered = [prompt for group in ((True, False), (True, True), (False, False), (False, True))
               for prompt in pool if fits(prompt) is group[0] and (prompt in stale) is group[1]]
    return tuple(ordered[position % len(ordered)] for position in range(count))


def _prose(text):
    """Drop the leading tag inventory so shared tags are not treated as copied prose."""
    value, position = str(text or ""), 0
    for tag in anima_tags(value):
        found = value.find(tag, position)
        if found < 0:
            break
        position = found + len(tag)
    return value[position:]


def copied_reference(text, references, words=10):
    """Return True when the prose of ``text`` repeats ``words`` consecutive words from a reference's prose."""
    tokens = re.findall(r"[a-z0-9]+", _prose(text).casefold())
    runs = {tuple(tokens[index:index + words]) for index in range(len(tokens) - words + 1)}
    for reference in references:
        source = re.findall(r"[a-z0-9]+", _prose(reference).casefold())
        if any(tuple(source[index:index + words]) in runs for index in range(len(source) - words + 1)):
            return True
    return False

"""Vocabulary selection: from the groups retrieval found (retrieval.py), the entries a set of images gets. Shared by
every category; the category's owner says which groups and how its entries go with another category's (pair).

diverse_order puts the groups in an order where each next one is unlike those before it, deal_spread deals the set
across them without repeating an entry before all have been dealt, and pair moves the dealt entries between the images
so each one goes with the other category's entry dealt to the same image.
"""

import math

from .embeddings import dot
from .retrieval import zscores


def diverse_order(groups, scores, vectors=None, balance=.5):
    """The groups ordered so each next one is relevant and unlike those before it (maximal marginal relevance):
    score minus how close it is to the closest group already chosen, weighed by balance. Without vectors, by score."""
    if not vectors:
        return [group for _, group in sorted(zip(scores, groups), key=lambda pair: -pair[0])]
    low, high = min(scores), max(scores)
    scaled = [(score - low) / (high - low) if high > low else 1.0 for score in scores]
    chosen, left = [], list(range(len(groups)))
    while left:
        best = max(left, key=lambda index: (1 - balance) * scaled[index] - balance * max(
            (dot(vectors[index], vectors[other]) for other in chosen), default=0.0))
        chosen.append(best)
        left.remove(best)
    return [groups[index] for index in chosen]


def deal_spread(groups, total, rng, locked=False):
    """{slot: entry}: each image from the next group in order, so a set spreads over as many groups as it has images;
    a group whose entries have all been dealt is passed over while another still has one, so no entry is dealt twice
    until every entry has been (a group of one never repeats while others have more). With locked, the first one for
    every image ({} without groups)."""
    groups = [group for group in groups if group["entries"]]
    if not groups:
        return {}
    decks, dealt, turn = [None] * len(groups), {}, 0  # None: not dealt from yet this round; []: all dealt
    for number in range(1, total + 1):
        if all(deck == [] for deck in decks):
            decks = [None] * len(groups)  # every entry has been dealt: start again
        index = next((turn + step) % len(groups) for step in range(len(groups))
                     if decks[(turn + step) % len(groups)] != [])
        if decks[index] is None:
            decks[index] = list(groups[index]["entries"])
            rng.shuffle(decks[index])
        dealt[number], turn = decks[index].pop(), index + 1
    return {number: dealt[1] for number in dealt} if locked else dealt


def pair(dealt, partners, fit):
    """{slot: entry}: the dealt entries moved between the images so each image's partner (another category's entry
    dealt to it) gets the dealt entry that goes with it best overall; the same entries, only swapped. fit(partner,
    entries) scores how well each entry goes with the partner (the category's own compatibility check); each partner's
    scores are compared over the dealt entries, so a partner that goes with every entry the same never moves one."""
    slots = [slot for slot in sorted(dealt) if slot in partners]
    if len(slots) < 2:
        return dict(dealt)
    pool = list(dict.fromkeys(dealt[slot] for slot in slots))
    scores = {partner: dict(zip(pool, zscores(fit(partner, pool)))) for partner in dict.fromkeys(partners[slot]
                                                                                                 for slot in slots)}
    matched = dict(dealt)
    gain = lambda a, b: (scores[partners[a]][matched[b]] + scores[partners[b]][matched[a]]
                         - scores[partners[a]][matched[a]] - scores[partners[b]][matched[b]])
    for _ in range(len(slots)):  # swap pairs while a swap improves the whole set
        best = max(((gain(a, b), a, b) for index, a in enumerate(slots) for b in slots[index + 1:]), default=(0, 0, 0))
        if best[0] <= 1e-9 or math.isnan(best[0]):
            break
        _, a, b = best
        matched[a], matched[b] = matched[b], matched[a]
    return matched

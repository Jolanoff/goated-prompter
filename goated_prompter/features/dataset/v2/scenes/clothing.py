"""Clothing from the user's selected Clothing packs: selecting one is the instruction to dress the people with it.

All the selected packs' entries are one pool. Every person who can be dressed (dressed: a human whose look is not a
known character's or a trigger's) wears one of them in every image, dealt per person (entries.deal_per_person); a
locked clothing part keeps each person's first one. An entry is one garment, not a whole outfit: the writer completes
the rest of the clothing. Packs made for one sex (a group named "female" or "male", like the built-in *-Female and
*-Male packs) dress only the people of that sex, and everyone else from the other selected packs (for_sex): the pack
says who it is for, so no garment is judged by its meaning. The request's garments come first, each on the person it
belongs to (entries.said_of).

No Clothing pack selected: nothing is dealt and the writer dresses everyone from the request. Adult sets keep their
rule (texts.NSFW_RULE): whoever takes part is bare unless the request, an entry or a selected Clothing entry names a
garment, so a selected pack stays a suggestion there and nothing is dealt.
"""

from ..understanding import is_human, stated_gender

CLOTHING = "Clothing"


def for_sex(packs, person):
    """The selected Clothing packs a person is dressed from: all but the ones made for the other sex (a pack whose
    group is named or worded "female" or "male": vocabulary/Clothing/*-Female.json and *-Male.json); all of them when
    the person's sex is unstated, or when only the other sex's packs are selected."""
    other = {"female": "male", "male": "female"}.get(stated_gender(person))
    says = lambda pack, word: any(word == group["name"].casefold() or word in group["words"]
                                  for group in pack.get("groups") or ())
    return [pack for pack in packs if not (other and says(pack, other))] or list(packs)


def dressed(person):
    """Whether a character is dealt clothing: a human whose look does not come from a name or trigger."""
    return is_human(person) and not person.get("known") and not person.get("triggers")

"""Resolve content profile and approved cast once per scoped Dataset request."""

from dataclasses import dataclass, replace

from .quality import (POSITION_ACT_CATEGORIES, adult_content_request, position_categories, requested_text, resolved_sex, sexual_request, ownership_request)
from .compatibility import participant_anatomy
from ...options.dataset import BODIED_KINDS, DATASET_SUBJECT_KINDS


@dataclass(frozen=True)
class ContentRoute:
    profile: str
    count: int
    sexes: tuple[str, ...]
    categories: frozenset[str]
    excluded: frozenset[str]
    scope: str
    kink: bool
    owned: bool
    subjects: tuple = ()
    sexual_action: bool = True
    request_text: str = ""

    @property
    def vocabulary_applicable(self):
        return self.profile == "adult" and self.sexual_action and (
            any(item["kind"] in BODIED_KINDS - {"animal"} for item in self.subjects) or not self.subjects and self.count > 0)

    @property
    def position_slots(self):
        expanded = [item for item in self.subjects for _ in range(item["count"])]
        return tuple(index for index, item in enumerate(expanded) if item["kind"] in BODIED_KINDS - {"animal"}) if expanded else tuple(range(self.count))


def scoped_request(data, scope):
    if not scope.startswith("guided:"):
        return {**data, "inputs": ""}
    lines = [line.strip() for line in str(data.get("inputs") or "").splitlines() if line.strip()]
    index = int(scope.split(":")[1]) - 1
    return {**data, "inputs": lines[index] if index < len(lines) else lines[0] if lines else ""}


def assignment_scope(data, index):
    lines = [line.strip() for line in str(data.get("inputs") or "").splitlines() if line.strip()]
    return f"guided:{(index - 1) % len(lines) + 1}" if data.get("source_mode") == "guided" and lines else "all_outputs"


def image_hard_requirements(data, scope):
    return tuple(dict.fromkeys(item["text"] for item in (data.get("_confirmed_intent") or {}).get("hard", ())
                               if item["scope"] in {scope, "all_outputs"}))


def resolve_routes(data, assignments):
    scopes = dict.fromkeys(assignment_scope(data, row["index"]) for row in assignments)
    return {scope: resolve_route(data, scope) for scope in scopes}


def resolve_route(data, scope="all_outputs"):
    brief = data.get("_confirmed_intent") or {}
    data = scoped_request(data, scope)
    supplied = [item for item in brief.get("subjects", ()) if item["scope"] in {scope, "all_outputs"}]
    described = {item["name"]: item for item in brief.get("characters", ())}
    supplied = [{**described.get(item["name"], {}), **item} for item in supplied]
    cast = supplied or brief.get("characters") or ()
    if not cast:
        kind = DATASET_SUBJECT_KINDS.get(data.get("trigger_type"), "other")
        count = brief.get("character_count") or 1
        cast = ({"name": "the subject", "kind": kind, "count": count, "sex": "unspecified" if kind in BODIED_KINDS else "none",
                 "traits": "", "origin": "described", "series": ""},)
    sexes = tuple("none" if item.get("sex") == "none" else resolved_sex(item, data) or "unspecified"
                  for item in cast for _ in range(item["count"]))
    count = len(sexes) or brief.get("character_count")
    if count is None:
        count = 0 if data.get("trigger_type") in {"Object / product", "Location / environment", "Visual style", "Brand / logo", "Typography / text"} or brief.get("identity_policy") == "not_applicable" else 1
    if not sexes:
        sexes = tuple("unspecified" for _ in range(count))
    categories, excluded = position_categories(data, include_director=False)
    adult = adult_content_request(data, include_director=False) and any(item["kind"] in BODIED_KINDS for item in cast)
    route = ContentRoute("adult" if adult else "general", count, sexes, frozenset(categories),
                         frozenset(excluded), scope, adult and "kink" in categories,
                         adult and ownership_request(data, include_director=False), tuple(cast), sexual_request(data, include_director=False),
                         requested_text(data, include_director=False) + "\n" + "\n".join(image_hard_requirements({"_confirmed_intent": brief}, scope)))
    if "penetration" in categories:
        categories.discard("penetration")
        if not categories & POSITION_ACT_CATEGORIES:
            categories.add("anal")
            if any("vagina" in parts for _, parts in participant_anatomy(route)):
                categories.add("vaginal")
    if "penetration" in excluded:
        excluded.update(("anal", "vaginal"))
    categories.difference_update(excluded)
    return replace(route, categories=frozenset(categories), excluded=frozenset(excluded), kink=adult and "kink" in categories)

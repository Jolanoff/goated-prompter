"""Data-defined interfaces reuse the canonical schemas and compatibility mechanisms.

Core declares its public interfaces in foundation.json. Packs may derive namespaced
interfaces from those contracts (or dependency-provided interfaces). Normalization
preserves the existing resolver's semantics; no pack can install executable rules.
"""

import jsonschema


class ComponentTypes:
    def __init__(self, packs, schema, scopes):
        self.schema, self.scopes = schema, scopes
        self.types = {name: {"base": name, "owner": None}
                      for name in schema["$defs"]["components"]["properties"]}
        self.validators = {name: jsonschema.Draft202012Validator({"$defs": schema["$defs"], **contract})
                           for name, contract in schema["$defs"]["components"]["properties"].items()}
        self.declarations = {}
        self.problems = []
        for pack in packs:
            for name, definition in pack.manifest.get("component_types", {}).items():
                if name in self.types or name in self.declarations:
                    self.problems.append(f"{pack.id}: duplicate component type {name}")
                elif not pack.mandatory and not name.startswith(pack.id + ":"):
                    self.problems.append(f"{pack.id}: component type {name} must use its pack namespace")
                else:
                    self.declarations[name] = (pack.id, definition)
        for name in self.declarations:
            self._resolve(name, set())

    def _resolve(self, name, trail):
        if name in self.types:
            return self.types[name]
        if name in trail or name not in self.declarations:
            self.problems.append(f"component type {name}: unknown base or inheritance cycle")
            return None
        owner, definition = self.declarations[name]
        parent = self._resolve(definition["base"], trail | {name})
        if parent is None:
            return None
        if parent["owner"] and parent["owner"] not in self.scopes[owner]:
            self.problems.append(f"{owner}: component type {name} requires {parent['owner']}")
        result = {**parent, **definition, "base": parent["base"], "owner": owner}
        if "dimension" in result and (result["base"] != "visual" or
                                       (parent.get("dimension") and parent["dimension"] != result["dimension"])):
            self.problems.append(f"{name}: incompatible visual dimension")
        self.types[name] = result
        return result

    def parts(self, components, owner, where):
        """Canonical component fragments, individually schema-checked before joint merging."""
        parts = []
        for name, value in components.items():
            definition = self.types.get(name)
            if definition is None:
                self.problems.append(f"{where}: unknown component type {name}")
                continue
            if definition["owner"] and definition["owner"] not in self.scopes[owner]:
                self.problems.append(f"{where}: component type {name} requires {definition['owner']}")
                continue
            value = {**({"dimension": definition["dimension"]} if "dimension" in definition else {}), **value}
            if "dimension" in definition and value.get("dimension") != definition["dimension"]:
                self.problems.append(f"{where}: {name} requires dimension {definition['dimension']}")
            base = definition["base"]
            # Canonical fields were already checked by the entry-file schema at load time.
            errors = list(self.validators[base].iter_errors(value)) if name != base else []
            for error in errors:
                self.problems.append(f"{where}/{name}: {error.message}")
            if not errors:
                parts.append({base: value})
        return parts

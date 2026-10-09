"""Strict JSON decoding helpers shared by workflow output parsers."""


def reject_duplicate_keys(message, error=ValueError):
    """Return a ``json.loads`` object-pairs hook that rejects repeated keys.

    Each workflow keeps its own user-facing message and exception type.
    """
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise error(message)
            result[key] = value
        return result
    return unique_object

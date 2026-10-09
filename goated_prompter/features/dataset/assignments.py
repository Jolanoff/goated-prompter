"""Assign guided inputs to dataset items without prescribing scene details."""


def dataset_assignments(data):
    lines = [line.strip() for line in str(data.get("inputs") or "").splitlines() if line.strip()]
    return [{"index": index + 1,
             "input": lines[index % len(lines)] if data.get("source_mode") == "guided" and lines else ""}
            for index in range(data["amount"])]

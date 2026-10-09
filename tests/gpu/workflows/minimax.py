"""MiniMax H3: the production MiniMaxService path with a fixed 10-second duration."""

SUBJECT_SCAFFOLD = False
TARGET = "MiniMax H3"
SAMPLE_SUFFIX = ""


def execute(row, context):
    from goated_prompter.minimax import MiniMaxService
    case, args = context.case, context.args
    result = MiniMaxService(context.config, lambda: None).run(context.request,
        {"user_request": case["request"], "planning_mode": args.planning,
         "duration_seconds": 10, "references": case.get("references", []), "director_preset": args.director},
        lambda _message: None)
    row["prompt"] = result["prompt"]

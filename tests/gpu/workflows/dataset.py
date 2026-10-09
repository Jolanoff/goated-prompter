"""Dataset: UNDERSTAND, human approval, then ideas, scenes and final enhancement."""

import json

SUBJECT_SCAFFOLD = True
TARGET = None
SAMPLE_SUFFIX = "|pipeline"


def approve_dataset(config, request, data):
    """Run UNDERSTAND and require a human to approve the interpretation before generation."""
    from goated_prompter.dataset_intent import DatasetIntentTickets
    from goated_prompter.dataset_understanding import DatasetUnderstandingService
    brief = DatasetUnderstandingService(config, lambda: None).run(request, data, print)
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    tickets = DatasetIntentTickets()
    ticket = tickets.register(data, brief)
    if not ticket["confirmation_token"] or input("Approve this interpretation? Type yes: ").strip() != "yes":
        raise ValueError("Dataset evaluation stopped before downstream generation.")
    return {**data, "_confirmed_intent": tickets.approve(ticket["confirmation_token"], data)}


def execute(row, context):
    from goated_prompter.dataset import DatasetService, default_dataset_draft
    case, args = context.case, context.args
    approve = context.approve or approve_dataset
    row["evaluation_scope"] = "pipeline"
    data = {**default_dataset_draft(), "subject": case["request"], "trigger": "eval_subject",
            "trigger_type": case.get("dataset_type", "Character"),
            "amount": 1, "target": args.target, "length": context.length, "director_preset": args.director,
            "creativity": args.creativity,
            "constraints": context.rules + "\n" + context.identity_rules}
    data.update(source_mode="guided", inputs=case["request"].replace("\n", " "))
    data = approve(context.config, context.request, data)
    result = DatasetService(context.config, lambda: None).run(context.request, data, lambda _message: None,
                                                              lambda _partial: None)
    row.update(scene_plan=result["scene_plan"], dataset_type=data["trigger_type"],
               completed_results=result["completed"], prompts=result["prompts"],
               prompt=result["prompts"][0]["prompt"] if result["prompts"] else "")
    if not result["completed"]:
        row.update(error="Dataset pipeline produced no valid prompt.", completion_state="validation_failed")

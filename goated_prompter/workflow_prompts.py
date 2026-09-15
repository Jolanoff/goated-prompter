"""Editable built-in behavior for the two creative workflows."""

DIRECTION_RULES = {
    "faithful": "Clarify the source with minimal invention. Keep its existing staging, mood, aesthetic and visual facts. Add only details needed to make the scene readable.",
    "creative": "Offer a distinct, plausible presentation of the SAME scene. Explore an unlocked and unspecified choice such as framing, focal hierarchy, depth, light treatment or palette accents. Do not replace specified scene facts to force variety.",
    "experimental": "Offer a bolder presentation of the SAME scene: for example unusual negative space, perspective, graphic framing or rendering treatment compatible with the requested medium. Choose only unlocked, unspecified decisions. Experimental does not mean a new location, weather, subject or story. Do not add surreal elements unless the source invites them.",
}

SCENE_CONTRACT = (
    "SOURCE ANCHORS: Each direction starts independently from SOURCE PROMPT, never by rewriting an earlier direction. "
    "Preserve all stated subjects, names, counts, appearances, outfits, actions, interactions, setting, time of day, "
    "weather, medium and character tag blocks, unless the source explicitly asks to explore alternatives to that fact. "
    "Unchecked locks allow compatible creative treatment, not erasing explicit source requirements. "
    "Vary presentation and fill useful unspecified details; do not force a minimum number of changes. "
    "Previous directions are only comparison examples, not additional requirements or replacement source facts. "
    "Keep the original specificity: never replace a named or described character with a generic protagonist or lone figure."
)

WRITING_STYLE = (
    "Write concrete visual content immediately. Avoid boilerplate openers such as 'A high-quality illustration featuring', "
    "generic quality slogans and vague cinematic/surreal restyling. Preserve the user's specified medium without replacing their scene with a stock genre scene."
)


def builtin_workflow_instructions(operation):
    if operation == "refine":
        return {"system": "Refine the supplied source prompt with the minimum changes needed to satisfy REQUESTED CHANGES. "
                "Preserve all unrelated details and the original intent. Shortening may compress wording without changing locked facts.\n\n" + WRITING_STYLE}
    if operation == "explore":
        return {"system": SCENE_CONTRACT + "\n\n" + WRITING_STYLE, **DIRECTION_RULES}
    raise ValueError("Unknown creative workflow.")

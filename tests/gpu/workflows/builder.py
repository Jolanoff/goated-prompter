"""Builder: the production GoatedPrompterService generation path."""

SUBJECT_SCAFFOLD = True
TARGET = None
SAMPLE_SUFFIX = ""


def execute(row, context):
    from goated_prompter.core import GoatedPrompterService
    row["prompt"] = GoatedPrompterService(config=context.config).generate(context.request).prompt

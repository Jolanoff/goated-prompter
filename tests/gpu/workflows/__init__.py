"""Real-engine workflow entry points, one module per workflow."""

from . import builder, dataset, minimax

WORKFLOWS = {"builder": builder, "dataset": dataset, "minimax": minimax}

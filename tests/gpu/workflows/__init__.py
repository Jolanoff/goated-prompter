"""Real-engine workflow entry points, one module per workflow."""

from . import builder, minimax

WORKFLOWS = {"builder": builder, "minimax": minimax}

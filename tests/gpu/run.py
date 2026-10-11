"""Real-engine evaluation through existing runners; --probe supporting-planning selects Direct/Auto."""

import argparse
import sys

from tests.support.safety import private_storage_guard


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--probe", choices=("workflow", "supporting-planning"), default="workflow")
    args, remaining = parser.parse_known_args(argv)
    if "--help" in remaining or "-h" in remaining:
        print(__doc__)
    if args.probe == "supporting-planning":
        from tests.evaluation.run_supporting_planning import main as run
    else:
        from tests.eval.runner import main as run
    return run(remaining, gpu=True)


if __name__ == "__main__":
    sys.addaudithook(private_storage_guard)
    sys.exit(main())

"""Run exactly one ingester in its own process.

Invoked by ``run_all_ingesters.py`` so that a hung or crashing ingester can be
killed without taking the rest of the run with it. Importing only the target
module keeps the child's startup at interpreter cost instead of importing all
twenty-odd ingesters.

Usage:
    python run_one_ingester.py data_ingest.ingest_eia

Prints a final ``INGEST_ROWS=<n>`` marker; the parent parses it and uses the
process exit code for success/failure. Any exception propagates, so the exit
code is non-zero and the traceback lands in the parent's log.
"""

import importlib
import sys


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: run_one_ingester.py <module>", file=sys.stderr)
        raise SystemExit(2)

    module = importlib.import_module(sys.argv[1])

    # Ingesters parse sys.argv in a few places; hide our own argument.
    original_argv = sys.argv
    sys.argv = [original_argv[0]]
    try:
        result = module.main()
    finally:
        sys.argv = original_argv

    rows = result if isinstance(result, int) else 0
    print(f"INGEST_ROWS={rows}", flush=True)


if __name__ == "__main__":
    main()

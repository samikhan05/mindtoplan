"""The one command: python plan.py <messages.txt>
First run (no .state/) plans from scratch; later runs process only messages not seen before.
Delete .state/ to start over."""
import sys
from pathlib import Path

from llm import ConfigError


def main():
    for stream in (sys.stdout, sys.stderr):   # piped/redirected output on Windows defaults to cp1252: "→" would crash
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) != 2:
        sys.exit("usage: python plan.py <messages.txt>")
    path = Path(sys.argv[1])
    if not path.exists():
        sys.exit(f"file not found: {path}")
    text = path.read_text(encoding="utf-8-sig")
    from pipeline import PREDICTED, process
    print(f"Prediction before this run: model calls only in area(s): {', '.join(PREDICTED)}")
    from report import print_run
    try:
        state, report = process(text, source=str(path))
    except ConfigError as e:
        sys.exit(f"Config error: {e}")
    print_run(state, report)


if __name__ == "__main__":
    main()

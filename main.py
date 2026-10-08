import sys

from infrastructure.logging_config import configure_logging
from interfaces.cli import main


if __name__ == "__main__":
    command = sys.argv[1].casefold() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "cli"
    configure_logging(command)
    raise SystemExit(main())

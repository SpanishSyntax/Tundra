"""Allow running Tundra via `python -m tundra`."""

import sys
from tundra.cli import main

if __name__ == "__main__":
    sys.exit(main())

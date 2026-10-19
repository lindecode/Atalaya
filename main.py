# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys

from infrastructure.logging_config import configure_logging
from interfaces.cli import main


if __name__ == "__main__":
    command = sys.argv[1].casefold() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "cli"
    configure_logging(command)
    raise SystemExit(main())

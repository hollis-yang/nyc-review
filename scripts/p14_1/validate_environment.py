#!/usr/bin/env python3
"""Validate every P14.1 isolation sentinel before running load."""

from __future__ import annotations

import json

from common import validate_isolated_environment


def main() -> int:
    print(json.dumps(validate_isolated_environment(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


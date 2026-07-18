# -*- coding: utf-8 -*-
"""Compatibility entrypoint. Prefer running fetch_all.py."""

from fetch_all import main


if __name__ == "__main__":
    raise SystemExit(main())

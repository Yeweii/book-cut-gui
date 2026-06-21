"""允许 `python -m book_cut` 调用。"""

from book_cut.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

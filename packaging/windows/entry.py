import os

from deektator.__main__ import main

if __name__ == "__main__":
    os.environ.pop("SD_ENABLE_ASIO", None)
    raise SystemExit(main())

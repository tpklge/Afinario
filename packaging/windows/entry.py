"""Entry shared by the windowed desktop and the console worker (hidden by its parent)."""

import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "--shazam-worker":
        from afinario.shazam_worker import main as worker_main

        del sys.argv[1]
        return worker_main()
    if len(sys.argv) > 1 and sys.argv[1] == "--worker-self-test":
        import json

        from shazamio import Shazam

        print(json.dumps({"shazamio": Shazam.__name__ == "Shazam"}))
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from afinario.bundle_check import main as check_main

        return check_main(sys.argv[2])
    from afinario.ui.app import main as desktop_main

    return desktop_main()


if __name__ == "__main__":
    raise SystemExit(main())

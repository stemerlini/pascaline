import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("-v", "--version"):
        from . import __version__

        print(f"pascaline {__version__}")
        return
    if len(sys.argv) > 1 and sys.argv[1] not in ("-h", "--help"):
        # One-shot mode: pascaline '2^10 + sqrt 2'
        from .app import one_line
        from .engine import Engine

        res = Engine().run(" ".join(sys.argv[1:]))
        print(res.text if res.kind == "error" else one_line(res))
        sys.exit(1 if res.kind == "error" else 0)
    if len(sys.argv) > 1:
        print("usage: pascaline [expression]   (no expression opens the notebook)")
        return
    from .app import Pascaline

    Pascaline().run()


if __name__ == "__main__":
    main()

"""Entry point of the packaged app: no arguments opens the Studio window; otherwise the `kinodraw` CLI."""
import multiprocessing
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == '--render-worker':
        from kinodraw.engine.render import main
        main(sys.argv[2:])
    elif len(sys.argv) > 1 and not sys.argv[1].startswith('-psn'):   # macOS passes -psn_… when opened from Finder
        from kinodraw.cli import main
        main()
    else:
        from kinodraw.studio.app import main
        main()

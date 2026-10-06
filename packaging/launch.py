"""Entry point of the packaged app: no arguments opens the Studio window; otherwise the `kinodraw` CLI."""
import multiprocessing
import sys
from pathlib import Path

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if len(sys.argv) > 1 and sys.argv[1] == '--render-worker':
        from kinodraw.engine.render import main
        main(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == '--finish-worker':
        from kinodraw.pipeline import finish_worker
        finish_worker(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == '--mcp-worker':
        from kinodraw.mcp_server import main
        raise SystemExit(main(sys.argv[2:]))
    elif len(sys.argv) > 1 and not sys.argv[1].startswith('-psn'):   # macOS passes -psn_… when opened from Finder
        from kinodraw.cli import main
        main()
    else:
        from kinodraw.studio.app import main
        main()

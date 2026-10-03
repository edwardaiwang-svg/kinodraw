"""Open KinoDraw: the local server plus a native window (or the default browser as a fallback)."""
from __future__ import annotations

import sys
import time
import webbrowser

from .. import paths
from .server import serve


def main(browser: bool = False, port: int = 0):
    paths.migrate()                     # once: Doodle Studio's folders become KinoDraw's
    server, url = serve(port)
    if not browser:
        try:
            import webview
            webview.create_window('KinoDraw', url, width=1320, height=880, min_size=(980, 640))
            webview.start()
            server.shutdown()
            return
        except Exception as error:  # noqa: BLE001 - no GUI toolkit (e.g. a bare Linux server): use the browser
            print(f'native window unavailable ({error}); opening your browser', file=sys.stderr)
    print(f'KinoDraw is running at {url}  (Ctrl+C to quit)')
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == '__main__':
    main('--browser' in sys.argv)

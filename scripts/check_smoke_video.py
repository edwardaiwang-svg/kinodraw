"""CI: check that the packaged app's smoke test made a real video.  usage: check_smoke_video.py <project folder>

The folder must hold one .mp4 with a size above zero and a duration above zero seconds (read by ffmpeg, not by the app)."""
import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

videos = sorted(Path(sys.argv[1]).glob('*.mp4'))
if len(videos) != 1:
    sys.exit(f'expected one .mp4 in {sys.argv[1]}, found {[v.name for v in videos]}')
video = videos[0]
report = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-i', str(video)], capture_output=True, encoding='utf-8',
                        errors='replace').stderr           # ffmpeg exits 1 with no output file; the report is on stderr
found = re.search(r'Duration: (\d+):(\d+):([\d.]+)', report)
seconds = int(found[1]) * 3600 + int(found[2]) * 60 + float(found[3]) if found else 0
size = video.stat().st_size
print(f'{video}: {size} bytes, {seconds:.2f} seconds')
if size == 0 or seconds <= 0:
    sys.exit(f'{video} is empty or has no duration')

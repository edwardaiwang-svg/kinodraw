# PyInstaller spec for Doodle Studio:  pyinstaller packaging/kinodraw.spec --noconfirm
# Output: dist/Doodle Studio.app (macOS) or dist/Doodle Studio/ (Windows, Linux).
# Voice models (~190 MB per language) download on first use, checksum-verified.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
datas, binaries, hidden = [], [], []
for package in ('kokoro_onnx', 'misaki', 'espeakng_loader', 'phonemizer', 'jieba', 'cn2an', 'num2words', 'fastembed',
                'onnxruntime', 'imageio_ffmpeg', 'resvg_py', 'webview', 'keyring', 'svgelements'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hidden += h
datas += [(str(ROOT / 'kinodraw' / 'assets'), 'kinodraw/assets'),
          (str(ROOT / 'kinodraw' / 'studio' / 'static'), 'kinodraw/studio/static'),
          (str(ROOT / 'LICENSE'), '.'), (str(ROOT / 'THIRD_PARTY_NOTICES.md'), '.'), (str(ROOT / 'LICENSES'), 'LICENSES')]
icon = {'darwin': 'icon.icns', 'win32': 'icon.ico'}.get(sys.platform)

a = Analysis([str(ROOT / 'packaging' / 'launch.py')], pathex=[str(ROOT)], datas=datas, binaries=binaries,
             hiddenimports=hidden, excludes=['tkinter', 'torch', 'matplotlib', 'IPython', 'pytest'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Doodle Studio', console=False,
          icon=str(ROOT / 'packaging' / icon) if icon else None)
coll = COLLECT(exe, a.binaries, a.datas, name='Doodle Studio')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='Doodle Studio.app', icon=str(ROOT / 'packaging' / 'icon.icns'),
                 bundle_identifier='io.github.kinodraw', version='0.1.6',
                 info_plist={'NSHighResolutionCapable': True, 'LSMinimumSystemVersion': '11.0'})

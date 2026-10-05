import os

# The app as videos credit it at the end ("Made with ..."): renaming the app changes this one line.
PRODUCT = {'name': 'KinoDraw', 'url': 'edwardaiwang-svg.github.io/kinodraw'}
VERSION = '0.3.0'        # as pyproject.toml and packaging/kinodraw.spec say (feedback names it)

# onnxruntime (the voice, the doodle search) would otherwise send Microsoft usage events with a device id
os.environ['ORT_DISABLE_TELEMETRY'] = '1'

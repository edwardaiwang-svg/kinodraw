import os

# The app as videos credit it at the end ("Made with ..."): renaming the app changes this one line.
PRODUCT = {'name': 'Doodle Studio', 'url': 'edwardaiwang-svg.github.io/doodle-studio'}

# onnxruntime (the voice, the doodle search) would otherwise send Microsoft usage events with a device id
os.environ['ORT_DISABLE_TELEMETRY'] = '1'

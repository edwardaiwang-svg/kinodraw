import os

# onnxruntime (the voice, the doodle search) would otherwise send Microsoft usage events with a device id
os.environ['ORT_DISABLE_TELEMETRY'] = '1'

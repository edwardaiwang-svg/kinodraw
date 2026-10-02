"""What the privacy page promises about the app itself."""
import os
import subprocess
import sys


def test_onnxruntime_is_told_not_to_report_usage():
    """onnxruntime (the voice, the doodle search) sends Microsoft usage events with a device id unless
    ORT_DISABLE_TELEMETRY is set before it loads; "no analytics and no tracking" means the app sets it first."""
    env = {k: v for k, v in os.environ.items() if k != 'ORT_DISABLE_TELEMETRY'}
    run = subprocess.run([sys.executable, '-c', 'import os, doodlestudio; print(os.environ.get("ORT_DISABLE_TELEMETRY"))'],
                         env=env, capture_output=True, text=True, check=True)
    assert run.stdout.strip() == '1'

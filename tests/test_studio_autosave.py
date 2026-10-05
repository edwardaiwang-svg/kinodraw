"""Execute the actual Studio DOM handlers against controlled HTTP responses."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / 'tests/studio_autosave_harness.js'


@pytest.mark.parametrize('scenario', ['title', 'raw-draft', 'late-error', 'adapted'])
def test_actual_input_handlers_and_controlled_save_responses(scenario):
    node = shutil.which('node')
    assert node, 'Node is required for the actual Studio input-handler regression'
    result = subprocess.run([node, str(HARNESS), scenario], cwd=ROOT, text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr

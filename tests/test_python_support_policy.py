"""Keep the supported runtime floor separate from portability analysis targets."""
from pathlib import Path
import tomllib

import yaml

import xprobe

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_metadata_and_lock_agree():
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    lock = tomllib.loads((ROOT / 'uv.lock').read_text(encoding='utf-8'))
    assert project['project']['requires-python'] == '>=3.11'
    assert lock['requires-python'] == project['project']['requires-python']


def test_stdlib_runtime_matrix_covers_supported_versions():
    workflow = yaml.safe_load((ROOT / '.github/workflows/runtime-compatibility.yml').read_text(encoding='utf-8'))
    job = workflow['jobs']['runtime']
    assert job['strategy']['matrix']['python'] == ['3.11', '3.12', '3.13', '3.14', '3.15']
    commands = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'python -S -m unittest discover -s tests -p test_xprobe.py -v' in commands
    assert 'python -S -m unittest discover -s tests -p test_text_runtime.py -v' in commands


def test_python310_analysis_target_is_not_the_runtime_floor(tmp_path):
    (tmp_path / 'example.py').write_text('import tomllib\n', encoding='utf-8')
    report = xprobe.portability_findings(tmp_path, min_python=(3, 10))
    assert report['min_python'] == [3, 10]
    assert any(item['kind'] == 'too_new' for item in report['findings'])
    assert xprobe.portability_findings(tmp_path)['min_python'] == [3, 10]

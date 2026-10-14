"""explain_outcome: conditions that separate an outcome, counterexamples, CLI."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

import xprobe

ROOT = Path(__file__).resolve().parents[1]


def presses():
    """Tall merged cards miss; plain buttons hit; one unexplained miss (r8)."""
    shape = [(40, 0, True), (44, 0, True), (38, 0, True), (42, 1, True), (122, 2, False),
             (130, 3, False), (125, 2, False), (118, 2, False), (41, 0, False)]
    return [{'label': f'r{i}', 'hit': {'self': hit}, 'box': {'height': h}, 'children': c, 'tags': ['x']}
            for i, (h, c, hit) in enumerate(shape)]


def test_best_condition_and_counterexamples():
    report = xprobe.explain_outcome(presses(), ('hit.self', False), id_field='label')
    best = report['results'][0]
    assert report['schema'] == 'xprobe.explain.v1' and report['target_rows'] == 5
    assert best['expr'] == 'box.height > 81' and best['predicates'] == 1
    assert (best['tp'], best['fp'], best['fn'], best['fn_ids']) == (4, 0, 1, ['r8'])
    assert best['mcc'] == pytest.approx(0.8)
    assert not any('label' in r['expr'] or 'hit.self' in r['expr'] for r in report['results'])


def test_same_rows_listed_once_and_compound_formulas():
    report = xprobe.explain_outcome(presses(), ('hit.self', False), top=50)
    selections = [(tuple(r['fp_ids']), tuple(r['fn_ids'])) for r in report['results']]
    assert len(selections) == len(set(selections))
    assert any(' and ' in r['expr'] for r in report['results'])
    assert any(' or ' in r['expr'] for r in report['results'])


def test_callable_target_thresholds_strings_and_missing_fields():
    rows = [{'n': i, 'kind': 'a' if i % 2 else 'b', 'opt': True if i == 3 else None} for i in range(40)]
    report = xprobe.explain_outcome(rows, lambda r: r['kind'] == 'a', skip=['kind'], max_thresholds=3,
                                    max_ids=2, top=1)
    assert report['predicate_count'] <= 3 * 2 + 1
    assert len(report['results'][0]['fp_ids']) <= 2
    preds = xprobe._predicates([xprobe._flatten(r) for r in rows], {'kind', 'n'}, 12, 8)
    assert preds == {'opt == true': 1 << 3}


def test_invalid_inputs():
    with pytest.raises(ValueError):
        xprobe.explain_outcome('x', ('a', 1))
    with pytest.raises(ValueError):
        xprobe.explain_outcome([{}], 'a=1')
    with pytest.raises(LookupError):
        xprobe.explain_outcome([{'a': 1}], ('b', 1))
    with pytest.raises(ValueError):
        xprobe.explain_outcome([{'a': 1}], ('a', 1), top=0)
    constant = xprobe.explain_outcome([{'a': 1, 'b': 1}, {'a': 1, 'b': 2}], ('b', 1))
    assert constant['results'] == []


def test_main_explain_modes(tmp_path, capsys, monkeypatch):
    path = tmp_path / 'p.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in presses()))
    assert xprobe.main(['--explain', str(path), '--target', 'hit.self=false', '--id', 'label', '--top', '2']) == 0
    out = capsys.readouterr().out
    assert out.count('mcc=') == 2 and 'fn: r8' in out
    cases = [{'id': 'c1', 'want': 'x', 'got': 'x', 'lang': 'en'}, {'id': 'c2', 'want': 'x', 'got': 'y', 'lang': 'zh'},
             {'id': 'c3', 'want': 'y', 'got': 'y', 'lang': 'en'}, {'id': 'c4', 'want': 'y', 'got': 'x', 'lang': 'zh'}]
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(cases)))
    assert xprobe.main(['--explain', '-', '--target-differs', 'want,got', '--id', 'id']) == 0
    out = capsys.readouterr().out
    assert '1. mcc=1.0000 tp=2 fp=0 fn=0  lang == "zh"' in out
    path2 = tmp_path / 'c.json'
    path2.write_text(json.dumps({'a': 1}))
    assert xprobe.main(['--explain', str(path2), '--target', 'a=1']) == 1
    assert xprobe.main(['--explain', str(path2), '--target', 'a']) == 2
    assert xprobe.main(['--explain', str(path2), '--target-differs', 'a']) == 2
    assert xprobe.main(['--explain', str(tmp_path / 'missing.json'), '--target', 'a=1']) == 2
    with pytest.raises(SystemExit):
        xprobe.main(['--explain', str(path2)])


def test_runs_standalone_under_python_dash_S(tmp_path):
    path = tmp_path / 'p.json'
    path.write_text(json.dumps(presses()))
    done = subprocess.run([sys.executable, '-S', str(ROOT / 'xprobe.py'), '--explain', str(path),
                           '--target', 'hit.self=false', '--top', '1'], capture_output=True, text=True)
    assert done.returncode == 0 and 'box.height > 81' in done.stdout

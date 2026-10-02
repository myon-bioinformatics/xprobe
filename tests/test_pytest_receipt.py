"""Shared receipt validation; consumer repos need only integration checks."""
import copy
import json
import pytest
import xprobe


def receipt(observations=(), *, status=0, repository='owner/repo', sha=None, run='sample'):
    context = dict(repository=repository, commit_sha=sha, report_id=run)
    counts = {}
    values = [('pytest_session', dict(event='start', schema='xprobe.pytest.v1'))]
    for phase, native, xfail, strict, outcome in observations:
        values.append(('pytest_observation', dict(event='report', phase=phase,
            native_outcome=native, wasxfail=xfail, strict_xpass=strict,
            outcome=outcome, node='test_example', node_hash='a' * 64)))
        counts[outcome] = counts.get(outcome, 0) + 1
    values.append(('pytest_session', dict(event='finish', complete=True, dropped=0,
        records_before_finish=len(values), exitstatus=status, phase_outcomes=counts)))
    return [dict(id=(repository or 'unmeasured') + '/' + run + '/' + str(i).zfill(6),
        category=kind, value=value, reason='Explicit observation', context=dict(context))
        for i, (kind, value) in enumerate(values)]


@pytest.mark.parametrize('status', range(6))
def test_status_is_not_reinterpreted_as_pass(status):
    rows = receipt(status=status)
    result = xprobe.pytest_receipt(reversed(rows), expected_context={'commit_sha': None})
    assert result['exitstatus'] == status
    assert result['observations'] == 0 and result['phase_counts'] == {}


def test_all_native_outcomes_and_identity():
    cases = [('setup', 'passed', False, False, 'passed'),
             ('call', 'failed', False, False, 'failed'),
             ('call', 'skipped', False, False, 'skipped'),
             ('call', 'skipped', True, False, 'xfail'),
             ('call', 'passed', True, False, 'xpass'),
             ('call', 'failed', True, False, 'failed'),
             ('call', 'failed', False, True, 'xpass_strict'),
             ('teardown', 'failed', False, False, 'error'),
             ('collection', 'failed', False, False, 'error')]
    rows = receipt(cases, status=1, sha='b' * 40)
    result = xprobe.pytest_receipt(rows, expected_context=rows[0]['context'])
    assert result['observations'] == len(cases)
    assert result['phase_counts']['teardown'] == {'error': 1}
    assert result['phase_outcomes']['failed'] == 2
    assert result['context'] == rows[0]['context']
    result['context']['report_id'] = 'changed'
    assert rows[0]['context']['report_id'] == 'sample'
    assert xprobe.pytest_receipt(receipt(repository=None))['context']['repository'] is None
    assert xprobe.pytest_receipt(receipt(sha='b' * 64))['context']['commit_sha'] == 'b' * 64


@pytest.mark.parametrize('selection', [[], [0], [1], [0, 0, 1], [0, 1, 1]])
def test_missing_or_duplicate_envelopes(selection):
    rows = receipt()
    with pytest.raises(ValueError):
        xprobe.pytest_receipt([rows[i] for i in selection])


@pytest.mark.parametrize('key,value', [
    ('repository', 'invalid'), ('repository', 3), ('commit_sha', 'short'),
    ('commit_sha', 'A' * 40), ('commit_sha', 3), ('report_id', 'bad/run'),
    ('report_id', None), ('report_id', 'a' * 129)])
def test_malformed_context(key, value):
    rows = receipt()
    for row in rows:
        row['context'][key] = value
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(rows)


@pytest.mark.parametrize('expected', [{'report_id': 'other'}, {'commit_sha': 'a' * 40},
    {'repository': 'other/repo'}, {'unknown': None}, []])
def test_expected_identity_is_checked(expected):
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(receipt(), expected_context=expected)


@pytest.mark.parametrize('index,path,value', [
    (0, ('context',), None), (0, ('context',), {}),
    (1, ('context', 'report_id'), 'other'), (1, ('id',), 'owner/repo/sample/000002'),
    (0, ('value',), []), (0, ('category',), 'other'),
    (0, ('value', 'event'), 'finish'), (0, ('value', 'schema'), 'future'),
    (1, ('category',), 'other'), (1, ('value', 'event'), 'start'),
    (1, ('value', 'complete'), False), (1, ('value', 'complete'), 1),
    (1, ('value', 'dropped'), 1), (1, ('value', 'dropped'), False),
    (1, ('value', 'records_before_finish'), 0),
    (1, ('value', 'records_before_finish'), True),
    (1, ('value', 'exitstatus'), True), (1, ('value', 'exitstatus'), -1),
    (1, ('value', 'exitstatus'), 6), (1, ('value', 'phase_outcomes'), []),
    (1, ('value', 'phase_outcomes'), {'passed': True}),
    (1, ('value', 'phase_outcomes'), {'passed': 0}),
    (1, ('value', 'phase_outcomes'), {'passed': 1})])
def test_corrupt_envelope(index, path, value):
    rows = receipt()
    target = rows[index]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(rows)


@pytest.mark.parametrize('key,value', [
    ('event', 'finish'), ('phase', 'unknown'), ('native_outcome', 'unknown'),
    ('wasxfail', 1), ('strict_xpass', 0), ('node', None), ('node', 'x' * 501),
    ('node_hash', None), ('node_hash', 'short'), ('outcome', 'passed'),
    ('strict_xpass', True)])
def test_corrupt_observation(key, value):
    rows = receipt([('teardown', 'failed', False, False, 'error')], status=1)
    rows[1]['value'][key] = value
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(rows)


def test_missing_report_and_mixed_run_are_not_complete():
    rows = receipt([('call', 'passed', False, False, 'passed')])
    with pytest.raises(ValueError):
        xprobe.pytest_receipt([rows[0], rows[-1]])
    other = receipt(run='other')
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(rows + other)
    rows[1]['category'] = 'pytest_session'
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(rows)
    rows = receipt(repository=None, sha='b' * 40)
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(rows)


def test_receipt_does_not_mutate_input():
    rows = receipt()
    original = copy.deepcopy(rows)
    xprobe.pytest_receipt(rows)
    assert rows == original


def test_raw_jsonl_validated_before_corpus_deduplication():
    rows = receipt()
    text = '\n'.join(json.dumps(row) for row in rows) + '\n'
    assert xprobe.pytest_receipt(text) == xprobe.pytest_receipt(rows)
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(text + json.dumps(rows[-1]))
    with pytest.raises(ValueError, match='duplicate JSON key'):
        xprobe.pytest_receipt(text.replace('"complete": true', '"complete": false, "complete": true'))
    with pytest.raises(ValueError):
        xprobe.pytest_receipt('{bad json}\n')
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(text.replace('"dropped": 0', '"dropped": NaN'))

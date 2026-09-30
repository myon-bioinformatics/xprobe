import re
from pathlib import Path

import pytest
import xprobe


@pytest.mark.parametrize('text,pattern,count', [
    ('', 'x', 0), ('日本日本', '日本', 2), ('aaaa', 'aa', 2),
    ('\x00PH0\x00', '\x00', 2), ('x\r\nx\nx', 'x', 3), ('🙂🙂', '🙂', 2)])
def test_search_input_matrix(text, pattern, count):
    assert len(xprobe.search_text(text, pattern)) == count


@pytest.mark.parametrize('value', [0, -1, True, None, '10', 1.5])
def test_file_limits_reject_invalid_values(tmp_path, value):
    with pytest.raises(ValueError):
        xprobe.search_files(tmp_path, 'x', max_bytes=value)
    with pytest.raises(ValueError):
        xprobe.search_files(tmp_path, 'x', max_matches=value)


@pytest.mark.parametrize('size,skipped', [(3, False), (4, True)])
def test_exact_byte_boundary(tmp_path, size, skipped):
    (tmp_path / 'a').write_bytes(b'x' * size)
    report = xprobe.search_files(tmp_path, 'x', max_bytes=3)
    assert bool(report['skipped']) is skipped
    assert bool(report['matches']) is not skipped


@pytest.mark.parametrize('case', [None, {}, {'name': 'a', 'value': 1},
    {'name': 'a', 'value': 1, 'expected': 1, 'raises': ValueError}])
def test_malformed_cases_do_not_execute(case):
    def forbidden(value):
        pytest.fail('invalid cases executed the target')
    with pytest.raises(ValueError):
        xprobe.run_cases(forbidden, [case])


def test_duplicate_names_rejected():
    case = {'name': 'n', 'value': 1, 'expected': 1}
    with pytest.raises(ValueError):
        xprobe.run_cases(int, [case, case])


def test_empty_cases_and_exception_subclass():
    assert xprobe.run_cases(int, []) == {'passed': True, 'results': []}
    assert xprobe.run_cases(int, [{'name': 'bad', 'value': None,
                                  'raises': Exception}])['passed']
    with pytest.raises(TypeError):
        xprobe.run_cases(None, [])


def test_walk_error_is_not_silent(tmp_path, monkeypatch):
    def failed_walk(root, *, followlinks, onerror):
        onerror(PermissionError(13, 'denied', str(tmp_path / 'sub')))
        return iter(())
    monkeypatch.setattr(xprobe.os, 'walk', failed_walk)
    report = xprobe.search_files(tmp_path, 'hit')
    assert report['errors'][0]['reason'] == 'PermissionError'


def test_hidden_directory_and_symlink_directory(tmp_path):
    target = tmp_path / 'dir'
    target.mkdir()
    (target / 'a').write_text('hit', encoding='utf-8')
    link = tmp_path / 'alias'
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('symlinks unavailable')
    assert [m['path'] for m in xprobe.search_files(tmp_path, 'hit')['matches']] == ['dir/a']


def test_encoding_and_text_type(tmp_path):
    (tmp_path / 'latin').write_bytes(b'caf\xe9')
    assert xprobe.search_files(tmp_path, 'café', encoding='latin-1')['matches']
    with pytest.raises(LookupError):
        xprobe.search_files(tmp_path, 'x', encoding='unknown-codec')
    with pytest.raises(TypeError):
        xprobe.search_text(b'x', 'x')

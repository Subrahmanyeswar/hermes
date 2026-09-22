import pytest
from tools.log_analyzer import count_by_level, filter_errors

def test_count_by_level():
    logs = ['[INFO] start', '[ERROR] db fail', '[WARN] memory high']
    result = count_by_level(logs)
    assert isinstance(result, dict)
    assert 'INFO' in result and result['INFO'] == 1
    assert 'ERROR' in result and result['ERROR'] == 1
    assert 'WARN' in result and result['WARN'] == 1

def test_filter_errors():
    logs = ['[INFO] start', '[ERROR] db fail', '[WARN] memory high']
    result = filter_errors(logs)
    assert isinstance(result, list)
    assert result == ['[ERROR] db fail']

if __name__ == '__main__':
    pytest.main()
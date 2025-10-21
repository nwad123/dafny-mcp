import os
import subprocess
import pytest
from unittest.mock import patch, Mock

from dafny import DafnyOptions, DafnyResult, DafnyError, run


def test_dafny_options_defaults():
    """Test that DafnyOptions has correct default values."""
    opts = DafnyOptions()
    assert opts.stdin == True
    assert opts.timeout == 60
    assert opts.json_output == False
    assert opts.cleanup == True
    assert opts.cores is None
    assert opts.verification_time_limit is None
    assert opts.resource_limit is None
    assert opts.extra_args == []


def test_dafny_options_command_building():
    """Test command line argument building."""
    # Test with defaults
    opts = DafnyOptions()
    cmd = opts.build_command("verify")
    assert cmd == ["dafny", "verify", "--stdin"]

    # Test with some options set
    opts = DafnyOptions(
        stdin=False,
        cores=4,
        verification_time_limit=30,
        json_output=True,
        extra_args=["--allow-warnings"]
    )
    cmd = opts.build_command("verify")
    assert cmd == [
        "dafny", "verify",
        "--cores", "4",
        "--verification-time-limit", "30",
        "--json-output",
        "--allow-warnings"
    ]


def test_dafny_options_validation():
    """Test that DafnyOptions validates inputs correctly."""
    # Test invalid timeout
    with pytest.raises(Exception):  # Pydantic validation error
        DafnyOptions(timeout=-1)

    # Test invalid cores
    with pytest.raises(Exception):
        DafnyOptions(cores=0)

    # Test invalid verification time limit
    with pytest.raises(Exception):
        DafnyOptions(verification_time_limit=-5)


def test_dafny_result_creation():
    """Test DafnyResult creation and conversion to dict."""
    result = DafnyResult(
        run_id="test-123",
        exit_code=0,
        stdout="Success",
        stderr="",
        cmd=["dafny", "verify"],
        tempdir=None
    )
    
    assert result.run_id == "test-123"
    assert result.exit_code == 0
    assert result.error_type is None

    # Test dict conversion
    result_dict = result.to_dict()
    assert result_dict["run_id"] == "test-123"
    assert result_dict["exit_code"] == 0
    assert "error" not in result_dict
    assert "timeout" not in result_dict


def test_dafny_result_timeout():
    """Test DafnyResult timeout factory method."""
    result = DafnyResult.from_timeout(
        run_id="timeout-123",
        cmd=["dafny", "verify"],
        timeout=60,
        stdout="partial output",
        stderr="",
        tempdir=None
    )
    
    assert result.error_type == DafnyError.TIMEOUT
    assert result.timeout_seconds == 60
    
    result_dict = result.to_dict()
    assert result_dict["error"] == "timeout"
    assert result_dict["timeout"] is True
    assert result_dict["timeout_seconds"] == 60


@patch('subprocess.run')
def test_run_success(mock_run):
    """Test successful Dafny execution."""
    # Mock successful subprocess execution
    mock_run.return_value = Mock(
        returncode=0,
        stdout=b"Success",
        stderr=b""
    )

    result = run("verify", "method Main() {}")
    
    assert result["exit_code"] == 0
    assert result["stdout"] == "Success"
    assert "error" not in result
    assert mock_run.called


@patch('subprocess.run')
def test_run_with_json_output(mock_run):
    """Test Dafny execution with JSON output parsing."""
    mock_run.return_value = Mock(
        returncode=0,
        stdout=b'{"status": "success"}',
        stderr=b""
    )

    result = run("verify", "method Main() {}", {"json_output": True})
    
    assert result["parsed_json"] == {"status": "success"}
    assert "parsed_json_error" not in result


@patch('subprocess.run')
def test_run_executable_not_found(mock_run):
    """Test handling of missing Dafny executable."""
    mock_run.side_effect = FileNotFoundError("dafny not found")

    result = run("verify", "method Main() {}")
    
    assert result["error"] == "executable_not_found"
    assert "dafny not found" in result["error_message"]
    assert result["exit_code"] is None


@patch('subprocess.run')
def test_run_timeout(mock_run):
    """Test handling of timeout during execution."""
    mock_run.side_effect = subprocess.TimeoutExpired(
        cmd=["dafny", "verify"],
        timeout=60,
        output=b"partial output",
        stderr=b"timeout occurred"
    )

    result = run("verify", "method Main() {}", {"timeout": 60})
    
    assert result["error"] == "timeout"
    assert result["timeout"] is True
    assert result["timeout_seconds"] == 60
    assert "partial output" in result["stdout"]
    assert "timeout occurred" in result["stderr"]
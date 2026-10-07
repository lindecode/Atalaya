import socket
import json

from interfaces.gui_instance import available_port, read_valid_instance


def test_available_port_skips_an_occupied_loopback_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]

        selected = available_port(port, attempts=2)

    assert selected == port + 1


def test_instance_file_cannot_claim_to_be_another_application(tmp_path):
    path = tmp_path / "gui-instance.json"
    path.write_text(json.dumps({"app": "Other", "version": 1, "port": 8501, "token": "x",
                                "pid": 1, "create_time": 1}), encoding="utf-8")

    assert read_valid_instance(path) is None


def test_expected_token_rejects_a_stale_or_forged_record(tmp_path):
    path = tmp_path / "gui-instance.json"
    path.write_text(json.dumps({"app": "Atalaya", "version": 1, "port": 8501, "token": "old",
                                "pid": 1, "create_time": 1}), encoding="utf-8")

    assert read_valid_instance(path, expected_token="current") is None

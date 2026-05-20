from copilot_fusion.server import create_server


def test_unified_server_construction() -> None:
    server = create_server()
    assert server is not None

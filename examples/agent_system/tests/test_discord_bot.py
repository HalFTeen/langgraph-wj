from examples.agent_system.gateway.discord_bot import _parse_command


def test_parse_command_approve() -> None:
    parsed = _parse_command("approve thread-1")
    assert parsed == ("approve", "thread-1", None)


def test_parse_command_deny() -> None:
    parsed = _parse_command("deny thread-2 reason here")
    assert parsed == ("deny", "thread-2", "reason here")


def test_parse_command_invalid() -> None:
    assert _parse_command("hello there") is None

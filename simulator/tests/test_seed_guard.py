"""The demo seed refuses to run outside a local or demo environment (Prompt 16)."""

import pytest

from nexira_sim.seed.__main__ import main


@pytest.mark.parametrize("app_env", ["pilot", "test", ""])
async def test_the_seed_refuses_anything_but_local_or_demo(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    with pytest.raises(SystemExit, match="seed refused"):
        await main()

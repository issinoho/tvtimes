"""PUT /api/account/source-alerts toggle + MeOut flag."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify


async def test_toggle_source_alerts(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))

    assert (await app_client.get("/api/account/me", headers=h)).json()[
        "source_alerts_enabled"
    ] is True

    off = await app_client.put("/api/account/source-alerts", headers=h, json={"enabled": False})
    assert off.status_code == 200, off.text
    assert (await app_client.get("/api/account/me", headers=h)).json()[
        "source_alerts_enabled"
    ] is False

    await app_client.put("/api/account/source-alerts", headers=h, json={"enabled": True})
    assert (await app_client.get("/api/account/me", headers=h)).json()[
        "source_alerts_enabled"
    ] is True

    assert (
        await app_client.put("/api/account/source-alerts", json={"enabled": False})
    ).status_code == 401

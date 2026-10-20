"""The WashRData panel in the sidebar: a plain web component served by the integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

PANEL_URL = DOMAIN
STATIC_URL = f"/{DOMAIN}_static"
ELEMENT = "washrdata-panel"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Without the HTTP server (as in some tests) there is nothing to serve."""
    if hass.http is None:
        return
    root = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(root), False)])
    # The version in the URL makes browsers load a new panel after an update.
    version = (await async_get_integration(hass, DOMAIN)).version
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="WashRData",
        sidebar_icon="mdi:washing-machine",
        frontend_url_path=PANEL_URL,
        require_admin=False,
        config={
            "_panel_custom": {
                "name": ELEMENT,
                "module_url": f"{STATIC_URL}/{ELEMENT}.js?v={version}",
                "embed_iframe": False,
                "trust_external": False,
            }
        },
    )

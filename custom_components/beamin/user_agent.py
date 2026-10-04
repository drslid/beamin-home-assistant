"""Light User-Agent parsing to describe the device asking to sign in.

The User-Agent is chosen by the requesting device, so the result is only a hint.
Labels come from a fixed vocabulary: raw header text never reaches logs or the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

KIND_CAR: Final = "car"
KIND_TV: Final = "tv"
KIND_TABLET: Final = "tablet"
KIND_PHONE: Final = "phone"
KIND_COMPUTER: Final = "computer"
KIND_UNKNOWN: Final = "unknown"

SHARED_KINDS: Final = frozenset({KIND_CAR, KIND_TV, KIND_TABLET})
MAX_USER_AGENT_LENGTH: Final = 512

# (pattern, kind, model); the first match wins, so specific devices come first.
_DEVICES: Final[tuple[tuple[re.Pattern[str], str, str], ...]] = tuple(
    (re.compile(pattern, re.IGNORECASE), kind, model)
    for pattern, kind, model in (
        (r"\bTesla/", KIND_CAR, "Tesla"),
        (r"\bAFT[A-Z0-9]*\b|Fire ?TV", KIND_TV, "Fire TV"),
        (r"\bCrKey/", KIND_TV, "Chromecast"),
        (r"Android TV|GoogleTV|\bBRAVIA\b|\bSHIELD\b", KIND_TV, "Android TV"),
        (r"Tizen.*\b(?:SMART-?TV|TV)\b|SMART-?TV.*Tizen", KIND_TV, "Samsung TV"),
        (r"Web0S|webOS.*\bTV\b|NetCast", KIND_TV, "LG TV"),
        (r"SMART-?TV|SmartTV|HbbTV|\bVIDAA\b", KIND_TV, "Smart TV"),
        (r"\biPad\b", KIND_TABLET, "iPad"),
        (r"\biPhone\b|\biPod\b", KIND_PHONE, "iPhone"),
        (r"Android.*\bMobile\b", KIND_PHONE, "Android phone"),
        (r"\bAndroid\b", KIND_TABLET, "Android tablet"),
        (r"\bCrOS\b", KIND_COMPUTER, "Chromebook"),
        (r"\bWindows\b", KIND_COMPUTER, "Windows PC"),
        (r"\bMacintosh\b|\bMac OS X\b", KIND_COMPUTER, "Mac"),
        (r"\bLinux\b|\bX11\b", KIND_COMPUTER, "Linux PC"),
    )
)

_BROWSERS: Final[tuple[tuple[re.Pattern[str], str], ...]] = tuple(
    (re.compile(pattern, re.IGNORECASE), name)
    for pattern, name in (
        (r"Home ?Assistant/", "Home Assistant app"),
        (r"\bEdg(?:e|A|iOS)?/", "Edge"),
        (r"\bOPR/|\bOpera\b", "Opera"),
        (r"SamsungBrowser/", "Samsung Internet"),
        (r"\bSilk/", "Silk"),
        (r"\bFirefox/|\bFxiOS/", "Firefox"),
        (r"\bCriOS/|\bChrome/|\bChromium/", "Chrome"),
        (r"\bSafari/", "Safari"),
    )
)


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """What the requesting browser says about itself."""

    kind: str
    model: str
    browser: str | None

    @property
    def label(self) -> str:
        """Return a short English description, e.g. "iPad (Safari)"."""
        if self.kind == KIND_CAR:
            return f"{self.model} browser"
        if self.browser is None:
            return self.model
        return f"{self.model} ({self.browser})"

    @property
    def shared(self) -> bool:
        """Return True for device types usually shared by several people."""
        return self.kind in SHARED_KINDS


def parse_user_agent(user_agent: str | None, *, touch: bool = False) -> DeviceInfo:
    """Describe a device from its User-Agent header.

    `touch` comes from the page (`navigator.maxTouchPoints > 1`): iPadOS sends a
    desktop Mac User-Agent, and touch support is what tells them apart.
    """
    text = (user_agent or "")[:MAX_USER_AGENT_LENGTH]
    kind, model = KIND_UNKNOWN, "Unknown device"
    for pattern, device_kind, device_model in _DEVICES:
        if pattern.search(text):
            kind, model = device_kind, device_model
            break
    if model == "Mac" and touch:
        kind, model = KIND_TABLET, "iPad"

    browser = next((name for pattern, name in _BROWSERS if pattern.search(text)), None)
    if kind == KIND_CAR:
        browser = None
    return DeviceInfo(kind=kind, model=model, browser=browser)

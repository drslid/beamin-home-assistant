"""Unit tests for rate limiting and User-Agent parsing."""

from __future__ import annotations

import pytest

from custom_components.beamin import rate_limit
from custom_components.beamin.rate_limit import (
    FailureLockout,
    SlidingWindowLimiter,
    ip_key,
)
from custom_components.beamin.user_agent import parse_user_agent


def test_sliding_window() -> None:
    """Events beyond the limit wait until the oldest leaves the window."""
    limiter = SlidingWindowLimiter(2, 60)
    assert limiter.hit("a", 0) is None
    assert limiter.hit("a", 10) is None
    assert limiter.hit("a", 20) == 40
    assert limiter.hit("b", 20) is None
    assert limiter.hit("a", 60.5) is None


def test_sliding_window_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rotating addresses cannot grow memory without bound."""
    monkeypatch.setattr(rate_limit, "MAX_TRACKED_KEYS", 3)
    limiter = SlidingWindowLimiter(1, 60)
    for key in ("a", "b", "c"):
        assert limiter.hit(key, 0) is None
    assert limiter.hit("d", 1) is None
    assert len(limiter._events) == 3
    assert limiter.hit("e", 100) is None
    assert set(limiter._events) == {"e"}


def test_lockout() -> None:
    """Failures within the window lock the key; the lock then expires."""
    lockout = FailureLockout(3, 300, 300)
    assert lockout.record_failure("u", 0) is False
    assert lockout.record_failure("u", 400) is False  # the first one aged out
    assert lockout.record_failure("u", 401) is False
    assert lockout.locked_for("u", 401) is None
    assert lockout.record_failure("u", 402) is True
    assert lockout.locked_for("u", 402) == 300
    assert lockout.locked_count(500) == 1
    assert lockout.locked_for("u", 702) is None
    assert lockout.locked_count(702) == 0


@pytest.mark.parametrize(
    ("ip", "key"),
    [
        ("203.0.113.5", "203.0.113.5"),
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
        ("::ffff:203.0.113.5", "203.0.113.5"),
        ("", ""),
    ],
)
def test_ip_key(ip: str, key: str) -> None:
    """IPv6 clients are grouped by /64."""
    assert ip_key(ip) == key


@pytest.mark.parametrize(
    ("user_agent", "touch", "kind", "label"),
    [
        (
            "Mozilla/5.0 (X11; GNU/Linux) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/109.0.5414.129 Safari/537.36 Tesla/2023.32.9-a1b2c3",
            False,
            "car",
            "Tesla browser",
        ),
        (
            "Mozilla/5.0 (Linux; Android 9; AFTMM Build/PS7633) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Silk/112.5.1 like Chrome/112.0.5615.213 Safari/537.36",
            False,
            "tv",
            "Fire TV (Silk)",
        ),
        (
            "Mozilla/5.0 (Linux; Android 12; BRAVIA 4K VH2 Build/STT1.211025.001) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            False,
            "tv",
            "Android TV (Chrome)",
        ),
        (
            "Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.5) AppleWebKit/537.36 "
            "(KHTML, like Gecko) SamsungBrowser/4.0 Chrome/85.0.4183.93 "
            "TV Safari/537.36",
            False,
            "tv",
            "Samsung TV (Samsung Internet)",
        ),
        (
            "Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/87.0.4280.88 Safari/537.36 WebAppManager",
            False,
            "tv",
            "LG TV (Chrome)",
        ),
        (
            "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
            True,
            "tablet",
            "iPad (Safari)",
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            True,
            "tablet",
            "iPad (Safari)",
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            False,
            "computer",
            "Mac (Safari)",
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/125.0 Mobile/15E148 "
            "Safari/604.1",
            True,
            "phone",
            "iPhone (Chrome)",
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Mobile Safari/537.36",
            True,
            "phone",
            "Android phone (Chrome)",
        ),
        (
            "Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            True,
            "tablet",
            "Android tablet (Chrome)",
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 Edg/125.0",
            False,
            "computer",
            "Windows PC (Edge)",
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
            False,
            "computer",
            "Linux PC (Firefox)",
        ),
        (
            "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            False,
            "computer",
            "Chromebook (Chrome)",
        ),
        (
            "Home Assistant/2024.10 (io.robbie.HomeAssistant; build:2024.1012; "
            "iOS 18.0.0) Mobile/HomeAssistant, like Safari",
            True,
            "unknown",
            "Unknown device (Home Assistant app)",
        ),
        ("", False, "unknown", "Unknown device"),
        (None, False, "unknown", "Unknown device"),
        ("<script>alert(1)</script>", False, "unknown", "Unknown device"),
    ],
)
def test_parse_user_agent(
    user_agent: str | None, touch: bool, kind: str, label: str
) -> None:
    """Devices are recognized from a fixed vocabulary."""
    device = parse_user_agent(user_agent, touch=touch)
    assert device.kind == kind
    assert device.label == label
    assert device.shared is (kind in ("car", "tv", "tablet"))

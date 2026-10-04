from __future__ import annotations

import sys

STEAMID64_INDIVIDUAL_BASE = 76561197960265728


def steam_id64_from_account_id(account_id: int) -> int:
    """Convert a 32-bit Steam AccountID to the usual individual SteamID64."""
    if not 0 < account_id <= 0xFFFFFFFF:
        raise ValueError("Steam AccountID must be between 1 and 4294967295")
    return STEAMID64_INDIVIDUAL_BASE + account_id


def validate_steam_id64(value: str | int) -> str:
    """Validate an individual-account SteamID64 and return its decimal string."""
    text = str(value)
    if not text.isdigit() or len(text) != 17:
        raise ValueError("SteamID64 must be a 17-digit decimal number")
    number = int(text)
    minimum = STEAMID64_INDIVIDUAL_BASE + 1
    maximum = STEAMID64_INDIVIDUAL_BASE + 0xFFFFFFFF
    if not minimum <= number <= maximum:
        raise ValueError(
            "SteamID64 is outside the normal individual-account range "
            f"{minimum}..{maximum}"
        )
    return text


def detect_active_steam_account_id() -> int | None:
    """Return Steam's active 32-bit AccountID on Windows, or None.

    Steam exposes the current account in:
      HKCU\\Software\\Valve\\Steam\\ActiveProcess\\ActiveUser
    """
    if sys.platform != "win32":
        return None

    try:
        import winreg
    except ImportError:
        return None

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Valve\Steam\ActiveProcess",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "ActiveUser")
    except OSError:
        return None

    try:
        account_id = int(value)
    except (TypeError, ValueError):
        return None
    if not 0 < account_id <= 0xFFFFFFFF:
        return None
    return account_id


def detect_active_steam_id64() -> int | None:
    account_id = detect_active_steam_account_id()
    if account_id is None:
        return None
    return steam_id64_from_account_id(account_id)


def resolve_steam_id(value: str | None) -> str | None:
    """Resolve a CLI SteamID value.

    - None: no SteamID metadata requested.
    - "auto": read the active Windows Steam account.
    - decimal value: validate it as a SteamID64.
    """
    if value is None:
        return None
    if value.lower() == "auto":
        detected = detect_active_steam_id64()
        if detected is None:
            raise ValueError(
                "could not detect an active Steam account. "
                "On Windows, start Steam and log into the target account, or "
                "pass a 17-digit SteamID64 explicitly."
            )
        return str(detected)
    return validate_steam_id64(value)

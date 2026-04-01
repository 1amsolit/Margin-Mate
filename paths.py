"""
Shared path helpers — works both when running from source and as a PyInstaller bundle.
"""
import os
import sys


def get_data_dir() -> str:
    """
    Return the directory where user data (orders.db, config.json) is stored.

    - Bundled app : platform-appropriate app-data folder so data survives updates.
    - Source run  : project root directory (existing behaviour).
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support/MarginMate")
        else:
            base = os.path.join(
                os.environ.get("APPDATA", os.path.expanduser("~")), "MarginMate"
            )
        os.makedirs(base, exist_ok=True)
        return base
    # Running from source — use the directory that contains this file
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir() -> str:
    """
    Return the directory that contains bundled assets (templates/, static/).

    - Bundled app : PyInstaller extracts them to sys._MEIPASS.
    - Source run  : project root directory.
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.abspath(__file__))

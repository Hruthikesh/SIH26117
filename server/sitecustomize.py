"""Auto-installs the YANTRA socket guard in every Python process that can import it.

Placed on PYTHONPATH by seal/env.py for all sealed child processes (engines, sandboxed
python, MCP servers). Must never break interpreter startup.
"""

try:
    from yantra_server.seal.socket_guard import install_from_env

    install_from_env()
except Exception:
    pass

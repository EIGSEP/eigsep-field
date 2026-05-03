# EIGSEP field shell environment.
#
# Sourced by /etc/profile for every login shell. Activates the system
# venv and points uv at it so `python`, `pip`, `uv pip`, and `uv sync`
# all hit /opt/eigsep/venv (no per-project .venv).

export VIRTUAL_ENV=/opt/eigsep/venv
export UV_PROJECT_ENVIRONMENT=/opt/eigsep/venv
export UV_CONFIG_FILE=/etc/eigsep/uv.toml
export EIGSEP_SRC=/opt/eigsep/src

case ":$PATH:" in
    *":/opt/eigsep/venv/bin:"*) ;;
    *) export PATH=/opt/eigsep/venv/bin:$PATH ;;
esac

if [ -n "${PS1:-}" ] && [ -r /opt/eigsep/CHEATSHEET.md ]; then
    echo "EIGSEP field node — see /opt/eigsep/CHEATSHEET.md"
fi

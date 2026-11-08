"""Shared config loading for claude-agenda and launchd-overdue (installed next to them).

The file is ~/.config/claude-agenda/config.json (or $CLAUDE_AGENDA_CONFIG). It lives outside the plugin
folder, so it survives plugin updates. seed() creates it (and the close-self allow-list and the yearly list)
from the starter files when missing; it never changes a file that exists. Run as a script with --seed (the
plugin's SessionStart hook) it does only that.
"""
import json
import os
import sys

DEFAULT_LABEL_PREFIX = "com.claude-agenda."


def home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def config_path():
    return os.environ.get("CLAUDE_AGENDA_CONFIG") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.join(home(), ".config"), "claude-agenda", "config.json")


def close_self_allow_path():
    """The allow-list claude-close-self reads (same rule as in that script)."""
    return os.environ.get("CLAUDE_CLOSE_SELF_ALLOW_FILE") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.join(home(), ".config"), "claude-agenda", "close-self-allow")


def yearly_path(cfg):
    """The yearly list launchd-overdue reads: env, else the yearly_file key, else the default."""
    return os.path.expanduser(os.environ.get("LAUNCHD_OVERDUE_YEARLY_FILE") or cfg.get("yearly_file")
                              or os.path.join(home(), ".config", "launchd-overdue", "yearly.txt"))


def _starter(name):
    """A starter file: next to the repo/plugin root (bin/..), or next to the tools as installed by install.sh
    (claude-agenda.<name>). None when neither exists."""
    here = os.path.dirname(os.path.realpath(__file__))
    for p in (os.path.join(os.path.dirname(here), name), os.path.join(here, "claude-agenda." + name)):
        if os.path.isfile(p):
            return p
    return None


def seed_file(dest, starter):
    """Copy starter to dest when dest does not exist. Never overwrites, never raises; returns dest when it
    wrote it, else None."""
    try:
        if not dest or not starter or os.path.lexists(dest):
            return None
        with open(starter, "rb") as f:
            data = f.read()
        parent = os.path.dirname(os.path.abspath(dest))
        os.makedirs(parent, exist_ok=True)
        # O_EXCL: if the file appears between the check and here, it is left alone
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except Exception:
            try:
                os.remove(dest)   # ours, created a moment ago: do not leave half a file
            except OSError:
                pass
            return None
        return dest
    except Exception:
        return None


def seed():
    """Create the config files that are missing from the starters. Silent; never raises."""
    written = []
    try:
        written.append(seed_file(config_path(), _starter("config.example.json")))
        written.append(seed_file(close_self_allow_path(), _starter("close-self-allow.example")))
        cfg = {}
        try:
            with open(config_path(), encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
        written.append(seed_file(yearly_path(cfg if isinstance(cfg, dict) else {}), _starter("yearly.example.txt")))
    except Exception:
        pass
    return [w for w in written if w]


def load_config(tool):
    """The config as a dict ({} when the file is absent). Exits with an error when it is not a JSON object."""
    path = config_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        sys.exit(f"{tool}: config file {path} is not valid JSON: {e}")
    if not isinstance(cfg, dict):
        sys.exit(f"{tool}: config file {path} must hold a JSON object")
    return cfg


def normalize_prefix(p):
    """A launchd label prefix always ends with '.'."""
    p = str(p or DEFAULT_LABEL_PREFIX)
    return p if p.endswith(".") else p + "."


def string_list(cfg, key, tool, check=None, rule=""):
    """cfg[key] as a list of non-empty strings ([] when unset). Exits with an error otherwise."""
    v = cfg.get(key)
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v) or \
            (check and not all(check(x) for x in v)):
        sys.exit(f"{tool}: {key} must be a list of non-empty strings{rule}; got {json.dumps(v)}")
    return v


if __name__ == "__main__":
    if "--seed" in sys.argv[1:]:
        seed()
    sys.exit(0)

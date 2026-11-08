"""Shared config loading for claude-agenda and launchd-overdue (installed next to them).

The file is ~/.config/claude-agenda/config.json (or $CLAUDE_AGENDA_CONFIG). It lives outside the plugin
folder, so it survives plugin updates.
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

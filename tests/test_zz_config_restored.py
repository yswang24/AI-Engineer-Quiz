"""Runs last alphabetically: the filter/export tests must restore config."""
from __future__ import annotations

import os
from pathlib import Path

from keepstack.config import config


def test_filters_module_restored_global_config():
    expected = Path(os.environ.get("KEEPSTACK_DATA_DIR", "data")).resolve()
    assert config.data_dir == expected
    assert "keepstack-filters-" not in str(config.data_dir)

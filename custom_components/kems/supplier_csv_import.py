"""Load owner-supplied Octopus meter CSVs from an optional local folder.

A user must explicitly copy source files to /config/kems_supplier_evidence/.
No network, Octopus credentials, core Recorder queries, automatic file writes,
or supplier data in the public GitHub integration distribution.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .kems_core.supplier_meter_reconciliation import parse_octopus_csv

MAX_SOURCE_BYTES = 2_000_000
FILENAMES = {
    "import": "octopus_import.csv",
    "export": "octopus_export.csv",
}


def read_local_supplier_csvs(directory: str) -> dict[str, Any]:
    """Read strictly fixed files, on an executor, bounded in size."""
    folder = Path(directory)
    output: dict[str, Any] = {
        "import": None,
        "export": None,
        "errors": {},
        "expected_directory": "/config/kems_supplier_evidence",
        "read_only": True,
    }
    if folder.is_symlink() or not folder.is_dir():
        output["errors"]["folder"] = "missing_or_symlink_directory"
        return output
    for direction, filename in FILENAMES.items():
        source = folder / filename
        if source.is_symlink():
            output["errors"][direction] = "symlink_rejected"
            continue
        if not source.is_file():
            output["errors"][direction] = "file_not_supplied"
            continue
        try:
            if source.stat().st_size > MAX_SOURCE_BYTES:
                output["errors"][direction] = "file_too_large"
                continue
            with source.open("rb") as file:
                raw = file.read(MAX_SOURCE_BYTES + 1)
            if len(raw) > MAX_SOURCE_BYTES:
                output["errors"][direction] = "file_too_large"
                continue
            output[direction] = parse_octopus_csv(
                raw.decode("utf-8-sig"), direction=direction
            )
        except (OSError, UnicodeError, ValueError, csv.Error) as error:
            output["errors"][direction] = type(error).__name__
    return output

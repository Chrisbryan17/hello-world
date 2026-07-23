#!/usr/bin/env python3
from pathlib import Path

source_path = Path(__file__).with_name("scan_copyable_wallets.py")
source = source_path.read_text(encoding="utf-8")
source = source.replace('"order": "end_date"', '"order": "endDate"')
namespace = {"__name__": "__main__", "__file__": str(source_path)}
exec(compile(source, str(source_path), "exec"), namespace)

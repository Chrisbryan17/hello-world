#!/usr/bin/env python3
from pathlib import Path

source_path = Path(__file__).with_name("scan_copyable_wallets.py")
source = source_path.read_text(encoding="utf-8")
source = source.replace('"order": "end_date"', '"order": "endDate"')
source = source.replace('"closed": "true",\n                "end_date_min"', '"closed": "true",\n                "tag_id": 21,\n                "related_tags": "true",\n                "end_date_min"')
source = source.replace('"limit": 500,', '"limit": 100,')
source = source.replace('if len(page) < 500:', 'if len(page) < 100:')
namespace = {"__name__": "__main__", "__file__": str(source_path)}
exec(compile(source, str(source_path), "exec"), namespace)

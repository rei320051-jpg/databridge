"""Audit a DataBridge CSV bundle and optionally import it to a new SQLite file."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from databridge.importer import QualityAudit, import_dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path, help='Folder containing metadata.json and three CSV files')
    parser.add_argument('--database', type=Path, help='Create this SQLite file only if checks pass')
    parser.add_argument('--report', type=Path, help='Write the complete JSON quality report')
    args = parser.parse_args()
    report = import_dataset(args.source, args.database) if args.database else QualityAudit(args.source).run()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)
    return 0 if report['error_count'] == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())

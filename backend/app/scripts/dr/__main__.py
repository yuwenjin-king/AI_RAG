"""DR 备份恢复 CLI：python -m app.scripts.dr {backup|restore|verify} [opts]（plan_three §6）。

详见 docs/dr-runbook.md。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.logging import setup_logging
from app.scripts.dr import backup as backup_mod
from app.scripts.dr import manifest as M
from app.scripts.dr import restore as restore_mod


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.scripts.dr", description="备份恢复 / DR（plan_three §6）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_b = sub.add_parser("backup", help="创建一份备份")
    p_b.add_argument("--out", default=None, help="备份根目录（默认 settings.backup_dir）")
    p_b.add_argument("--id", default=None, help="指定 backup_id（默认自动 UTC 时间戳）")

    p_r = sub.add_parser("restore", help="从备份恢复（破坏性：清空并重写目标存储）")
    p_r.add_argument("path", help="备份目录（含 manifest.json）")
    p_r.add_argument("--no-verify", action="store_true", help="跳过 sha256 完整性校验（不推荐）")
    p_r.add_argument("--yes", action="store_true", help="跳过交互确认")

    p_v = sub.add_parser("verify", help="仅校验备份完整性（sha256 + 权威源）")
    p_v.add_argument("path", help="备份目录")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    setup_logging()

    if args.cmd == "backup":
        man = asyncio.run(backup_mod.backup(args.out, backup_id=args.id))
        print(json.dumps(
            {
                "backup_id": man.backup_id,
                "status": man.status,
                "stores": [a.store for a in man.stores],
                "notes": man.notes,
            },
            ensure_ascii=False, indent=2,
        ))
        return

    if args.cmd == "verify":
        bdir = Path(args.path)
        man = M.read_manifest(bdir)
        report = M.verify_manifest(man, bdir)
        print(json.dumps(
            {
                "backup_id": man.backup_id,
                "status": man.status,
                "passed": report.passed,
                "ok": report.ok,
                "missing": report.missing,
                "mismatched": report.mismatched,
                "recoverable": report.recoverable,
            },
            ensure_ascii=False, indent=2,
        ))
        sys.exit(0 if report.passed else 1)

    if args.cmd == "restore":
        if not args.yes:
            confirm = input("⚠️  这将清空并重写目标存储（PG/Milvus/MinIO/OpenSearch）。输入 yes 继续： ")
            if confirm.strip().lower() != "yes":
                print("已取消。")
                sys.exit(1)
        try:
            res = asyncio.run(restore_mod.restore(args.path, verify=not args.no_verify))
        except restore_mod.VerifyError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
            sys.exit(2)
        print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

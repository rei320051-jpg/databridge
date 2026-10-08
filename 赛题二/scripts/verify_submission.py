"""Verify every packaged hash, then test the extracted tree without source/env fallback."""
import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    # Temporary path belongs only to this run; it is cleaned after tests.
    with tempfile.TemporaryDirectory(prefix='submission-check-', dir=ROOT / 'outputs') as folder:
        target = Path(folder)
        with zipfile.ZipFile(args.package) as archive:
            names = archive.namelist()
            roots = {PurePosixPath(name).parts[0] for name in names}
            if len(roots) != 1:
                raise SystemExit('包必须只有一个根目录')
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                    raise SystemExit('包内存在不安全路径')
            archive.extractall(target)
        extracted = target / next(iter(roots))
        checks = 0
        for line in (extracted / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
            expected, name = line.split('  ', 1)
            resolved = (extracted / name).resolve()
            if not resolved.is_relative_to(extracted.resolve()):
                raise SystemExit('校验文件存在不安全路径')
            if hashlib.sha256(resolved.read_bytes()).hexdigest() != expected:
                raise SystemExit(f'SHA256失配：{name}')
            checks += 1
        print(f'PASS 解包 SHA256：{checks} 个文件', flush=True)
        environment = os.environ.copy()
        for name in ('DATABRIDGE_DATABASE', 'DATABRIDGE_RECORDS', 'DATABRIDGE_BACKEND',
                     'DATABRIDGE_API', 'PYTHONPATH'):
            environment.pop(name, None)
        environment.update(DATABRIDGE_AGENT_MODE='rules', PYTHONUTF8='1', PYTHONWARNINGS='ignore')
        result = subprocess.run([sys.executable, 'tests/formal_delivery_test.py'], cwd=extracted,
                                env=environment, timeout=180,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        if result.returncode:
            raise SystemExit(result.returncode)
        print('PASS 独立解包目录：正式默认库、质检、真实页面 HTTP 连查三次；无源代码/环境变量回退')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

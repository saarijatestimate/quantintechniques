import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'select_env.py'


class SelectEnvTests(unittest.TestCase):
    def test_select_env_writes_expected_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            env_dir = tmp_root / 'env'
            env_dir.mkdir()
            (env_dir / 'int.env').write_text('APP_ENV=int\nAPI_URL=https://api-int.example.com\n', encoding='utf-8')

            target = tmp_root / '.env'
            result = subprocess.run(
                [sys.executable, str(SCRIPT), 'int', '--root', str(tmp_root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(target.exists())
            self.assertIn('APP_ENV=int', target.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()

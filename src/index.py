from pathlib import Path

root = Path(__file__).resolve().parents[1]
env_file = root / '.env'

print('Environment configuration loaded')

if env_file.exists():
    for line in env_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        print(f'{key.strip()}={value.strip()}')
else:
    print('No .env file found. Run: py scripts/select_env.py int')

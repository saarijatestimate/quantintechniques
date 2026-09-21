import argparse
import sys
from pathlib import Path

VALID_ENVS = ('int', 'syst', 'accept')


def select_environment(env_name: str, root_dir: Path) -> None:
    if env_name not in VALID_ENVS:
        raise ValueError(f'Environment must be one of: {VALID_ENVS}')

    source = root_dir / 'env' / f'{env_name}.env'
    target = root_dir / '.env'

    if not source.exists():
        raise FileNotFoundError(f'Environment file not found: {source}')

    target.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
    print(f'Selected environment: {env_name}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Select int, syst, or accept environment configuration.')
    parser.add_argument('environment', choices=VALID_ENVS, help='Environment name')
    parser.add_argument(
        '--root',
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help='Project root directory',
    )
    args = parser.parse_args()

    try:
        select_environment(args.environment, args.root)
        return 0
    except Exception as exc:  # pragma: no cover - CLI error handling
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

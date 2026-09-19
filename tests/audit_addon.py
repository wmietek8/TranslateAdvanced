"""Audit a built release, without loading it into the running NVDA instance."""
import argparse
import gettext
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('addon')
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--secret-file', action='append', default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    artifact = Path(args.addon)
    secrets = set()
    secret_fields = {'key', 'access_token', 'refresh_token', 'id_token', 'OPENAI_API_KEY'}

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in secret_fields and isinstance(item, str) and len(item) >= 8:
                    secrets.add(item.encode('utf-8'))
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    for path in args.secret_file:
        collect(json.loads(Path(path).read_text(encoding='utf-8')))
    code_count = 0
    with zipfile.ZipFile(artifact) as archive:
        assert archive.testzip() is None, 'ZIP integrity failure'
        names = archive.namelist()
        assert len(names) == len(set(names)), 'Duplicate archive members'
        forbidden = []
        for name in names:
            parts = PurePosixPath(name).parts
            assert '..' not in parts and not name.startswith('/'), 'Unsafe archive path'
            if any(part.lower() in {'__pycache__', '.git', '.pytest_cache', 'tests', 'codex'} for part in parts):
                forbidden.append(name)
            if PurePosixPath(name).name.lower() in {'auth.json', 'apis.json', '.env'} or name.endswith(('.pyc', '.pyo', '.log')):
                forbidden.append(name)
            data = archive.read(name)
            assert not any(secret in data for secret in secrets), 'Private credential detected in release member: ' + name
            if name.endswith('.py'):
                source = data.decode('utf-8-sig')
                compile(source, name, 'exec')
                local = (root / 'addon' / name).read_text(encoding='utf-8-sig')
                assert source.replace('\r\n', '\n') == local.replace('\r\n', '\n'), 'Stale packaged code: ' + name
                code_count += 1
        assert not forbidden, 'Forbidden release members: ' + repr(forbidden)
        expected_sources = {p.relative_to(root / 'addon').as_posix() for p in (root / 'addon').rglob('*.py')}
        assert expected_sources == {n for n in names if n.endswith('.py')}, 'Missing or extra Python sources'
        manifest = archive.read('manifest.ini').decode('utf-8-sig')
        values = dict(line.split('=', 1) for line in manifest.splitlines() if '=' in line)
        values = {key.strip(): value.strip().strip('"') for key, value in values.items()}
        assert values['version'] == args.version
        assert 'Héctor' in values['author'] and 'wmietek8' in values['author']
        assert archive.read('COPYING.txt') == (root / 'COPYING.txt').read_bytes()
        assert archive.read('MODIFICATIONS.md') == (root / 'MODIFICATIONS.md').read_bytes()
        assert archive.read('VALIDATION.md') == (root / 'VALIDATION.md').read_bytes()
        for language in ('pl', 'en'):
            html = archive.read(f'doc/{language}/readme.html').decode('utf-8')
            assert args.version in html and 'OpenAI' in html and 'OAuth' in html
        polish = gettext.GNUTranslations(io.BytesIO(archive.read('locale/pl/LC_MESSAGES/nvda.mo')))
        for message in ('Clipboard changed. Translation was not copied.', 'S&tatus:'):
            assert polish.gettext(message) != message, 'Missing packaged Polish translation'
    report = {
        'version': args.version, 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
        'bytes': artifact.stat().st_size, 'archive_members': len(names),
        'python_sources_compiled_and_matched': code_count,
        'all_sources_present': True, 'zip_integrity': True,
        'polish_catalog_and_pl_en_help': True,
        'gpl_and_original_author_preserved': True,
        'private_secret_values_checked': len(secrets),
        'private_credentials_found': False, 'forbidden_files_found': False,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Verify the Git source subset against the published full-delivery manifest."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'source'
    layout = json.loads((source / 'UPSTREAM_LAYOUT.json').read_text(encoding='utf8'))
    manifest = json.loads((source / 'FILE_MANIFEST.json').read_text(encoding='utf8'))
    mismatches = []
    checked = 0
    for name in layout.get('git_snapshot_files', layout.get('git_original_files', [])):
        if name not in manifest:
            # FILE_MANIFEST itself and later-generated source manifests are
            # authenticated by the repository-wide FILES.json instead.
            continue
        path = source / name
        expected = manifest[name]
        if not path.is_file():
            mismatches.append(name)
            continue
        data = path.read_bytes()
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            mismatches.append(name)
        checked += 1
    public_inventory = json.loads((ROOT / 'FILES.json').read_text(encoding='utf8'))
    for entry in public_inventory:
        if not entry['file'].startswith('source/'):
            continue
        path = ROOT / entry['file']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            mismatches.append('repository: ' + entry['file'])
    print(json.dumps({'passed': not mismatches, 'release_manifest_files_checked': checked,
                      'release_only_files': len(layout['release_only_files']),
                      'mismatched_files': mismatches}, indent=2))
    return int(bool(mismatches))


if __name__ == '__main__':
    raise SystemExit(main())

import hashlib
import json
from zipfile import ZipFile

import pytest

from experiments.archive import FILES, archive_results


def test_archive_contains_evidence_checksums_and_no_environment(tmp_path):
    source = tmp_path / 'results'
    experiment = source / 'rps' / 'run1'
    experiment.mkdir(parents=True)
    for name in FILES:
        (experiment / name).write_text('{}')
    (source / '.env').write_text('SECRET=do-not-copy')
    output = tmp_path / 'archive.zip'
    assert archive_results(source, output) == 1
    with ZipFile(output) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        assert set(bundle.namelist()) == {'manifest.json', *(f'rps/run1/{n}' for n in FILES)}
        for name, digest in manifest['sha256'].items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == digest
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        archive_results(source, output)
    assert output.read_bytes() == before


def test_archive_rejects_missing_source_data(tmp_path):
    with pytest.raises(ValueError, match='no completed'):
        archive_results(tmp_path, tmp_path / 'empty.zip')
    assert not (tmp_path / 'empty.zip').exists()

"""FAILING regression tests that document mainline implementation gaps.

These tests assert the *desired* offline contract for the Render B-02
"worker produces artifacts, web downloads across containers" flow. They
fail against the current production code on purpose: they are the
regression baseline the mainline must make pass. Do NOT mark them
xfail — a green suite here means the gap was fixed in mainline.

Gaps documented (see the suite report):
  G-1  A stale local same-name file shadows the authoritative remote
       bytes (and the remote size) on both list() and resolve().
  G-2  No integrity digest: corrupted remote bytes with a plausible
       size are served silently.
  G-3  JSON artifacts cannot round-trip across containers: the stored
       application/json content-type makes the client's own _request
       parse the payload, so get_bytes() rejects it and the web falls
       back to a uniform 404.
"""

import json

import pytest
from fastapi import HTTPException

from fakes import (
    FakeQoderStorage,
    make_web_store,
    make_worker_client,
    sign,
)


def test_regression_g1_stale_local_copy_shadows_authoritative_remote_bytes(
    tmp_path, monkeypatch,
):
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    authoritative = b'PK-authoritative-v2-bytes'
    worker.put_bytes(
        'task-1', 'report.docx', authoritative,
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )

    # The web container still carries the previous run's local copy.
    web_fs = tmp_path / 'web'
    (web_fs / 'task-1').mkdir(parents=True)
    (web_fs / 'task-1' / 'report.docx').write_bytes(b'PK-stale-v1-bytes')

    store = make_web_store(web_fs, monkeypatch, storage)

    listed = {item['name']: item['size'] for item in store.list('task-1', 'owner-1')}
    assert listed['report.docx'] == len(authoritative), (
        'list() reports the stale local size instead of the authoritative remote size'
    )

    resolved = store.resolve(
        'task-1', 'report.docx', 'owner-1', sign(store, filename='report.docx'),
    )
    served = (
        resolved.content if isinstance(resolved.content, bytes)
        else resolved.read_bytes()
    )
    assert served == authoritative, (
        'resolve() served stale local bytes while newer authoritative '
        'remote bytes exist for the same artifact name'
    )


def test_regression_g2_corrupted_remote_bytes_are_served_silently(
    tmp_path, monkeypatch,
):
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    payload = b'PK' + bytes(range(256)) * 64
    worker.put_bytes('task-1', 'report.docx', payload, 'application/octet-stream')
    recorded_digest = storage.get('artifacts/task-1/report.docx')['sha256']

    # Corrupt exactly one byte in place: size stays plausible, no digest
    # channel exists, so the web side has nothing to compare against.
    corrupted = bytearray(payload)
    corrupted[len(corrupted) // 2] ^= 0xFF
    storage.objects['artifacts/task-1/report.docx']['body'] = bytes(corrupted)

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)

    import hashlib
    assert hashlib.sha256(bytes(corrupted)).hexdigest() != recorded_digest
    try:
        store.resolve(
            'task-1', 'report.docx', 'owner-1', sign(store, filename='report.docx'),
        )
    except HTTPException:
        return  # desired behavior once the integrity channel exists
    pytest.fail(
        'resolve() served bytes whose SHA-256 diverges from the digest '
        'recorded at upload time; the artifact flow has no integrity check',
        pytrace=False,
    )


def test_regression_g3_json_artifact_cannot_round_trip_across_containers(
    tmp_path, monkeypatch,
):
    storage = FakeQoderStorage()
    worker = make_worker_client(storage)
    payload = json.dumps(
        {'series': [1, 2, 3], 'label': '仪表盘'},
        ensure_ascii=False,
    ).encode('utf-8')
    # The worker's content-type mapping stores JSON as application/json.
    worker.put_bytes(
        'task-1', 'dashboard_data.json', payload, 'application/json; charset=utf-8',
    )

    web_fs = tmp_path / 'web'
    web_fs.mkdir()
    store = make_web_store(web_fs, monkeypatch, storage)

    listed = {item['name']: item['size'] for item in store.list('task-1', 'owner-1')}
    assert listed['dashboard_data.json'] == len(payload)

    resolved = store.resolve(
        'task-1', 'dashboard_data.json', 'owner-1',
        sign(store, filename='dashboard_data.json'),
    )
    assert resolved.content == payload

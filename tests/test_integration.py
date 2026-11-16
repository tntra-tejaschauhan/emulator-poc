"""Integration tests against the live AWS Emulator.

Skipped with a clear message when the emulator is unreachable or the account
is not the emulator's. Tests use their own resource names (``poc-test-*``)
and delete them afterwards, so they never touch the demo's ``poc-files``.
"""

import hashlib
import json
import os

import botocore.exceptions
import pytest
from fastapi.testclient import TestClient

from app import bootstrap, worker
from app.aws import check_emulator, get_client
from app.config import EMULATOR_ACCOUNT_ID
from app.main import app
from app.processing import process_file_content

TEST_BUCKET = "poc-test-files"
TEST_TABLE = "poc-test-files"
TEST_QUEUE = "poc-test-file-jobs"

EXPECTED_ENDPOINT = "https://127.0.0.1:9297"


@pytest.fixture(scope="session")
def emulator():
    reachable, account = check_emulator()
    if not reachable:
        pytest.skip("emulator not reachable (start it and source scripts/env.sh)")
    if account != EMULATOR_ACCOUNT_ID:
        pytest.skip(f"AWS account is {account}, not the emulator's "
                    f"({EMULATOR_ACCOUNT_ID}); refusing to run integration tests")


@pytest.fixture(scope="session")
def test_resources(emulator):
    old = {k: os.environ.get(k) for k in ("BUCKET_NAME", "TABLE_NAME", "QUEUE_NAME")}
    os.environ.update({"BUCKET_NAME": TEST_BUCKET, "TABLE_NAME": TEST_TABLE,
                       "QUEUE_NAME": TEST_QUEUE})
    try:
        bootstrap.ensure_all()
        # Clean slate: drop messages left by an earlier crashed run.
        sqs = get_client("sqs")
        sqs.purge_queue(QueueUrl=sqs.get_queue_url(QueueName=TEST_QUEUE)["QueueUrl"])
        yield {"bucket": TEST_BUCKET, "table": TEST_TABLE, "queue": TEST_QUEUE}
    finally:
        try:
            _delete_test_resources()
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _delete_test_resources():
    """Best-effort cleanup of the test bucket/table/queue."""
    s3, ddb, sqs = get_client("s3"), get_client("dynamodb"), get_client("sqs")
    try:
        listed = s3.list_objects_v2(Bucket=TEST_BUCKET).get("Contents", [])
        for obj in listed:
            s3.delete_object(Bucket=TEST_BUCKET, Key=obj["Key"])
        s3.delete_bucket(Bucket=TEST_BUCKET)
    except botocore.exceptions.ClientError as exc:
        print(f"cleanup: bucket: {exc}")
    try:
        ddb.delete_table(TableName=TEST_TABLE)
    except botocore.exceptions.ClientError as exc:
        print(f"cleanup: table: {exc}")
    try:
        url = sqs.get_queue_url(QueueName=TEST_QUEUE)["QueueUrl"]
        sqs.delete_queue(QueueUrl=url)
    except botocore.exceptions.ClientError as exc:
        print(f"cleanup: queue: {exc}")


@pytest.fixture()
def client(test_resources):
    with TestClient(app) as test_client:
        yield test_client


def _upload(client, payload: bytes, filename="sample.txt",
            content_type="text/plain"):
    response = client.post("/files", files={"file": (filename, payload, content_type)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PENDING"
    return body["file_id"]


def test_full_flow_upload_process_fetch(client):
    payload = b"hello emulator\nline two has words\n"
    file_id = _upload(client, payload)

    counts = worker.drain_queue()
    assert counts["processed"] == 1, counts

    fetched = client.get(f"/files/{file_id}")
    assert fetched.status_code == 200
    item = fetched.json()
    expected = process_file_content(payload)
    assert item["status"] == "PROCESSED"
    assert item["size_bytes"] == expected["size_bytes"] == len(payload)
    assert item["line_count"] == expected["line_count"] == 2
    assert item["word_count"] == expected["word_count"] == 6
    assert item["sha256"] == expected["sha256"] == hashlib.sha256(payload).hexdigest()
    assert item["filename"] == "sample.txt"
    assert "processed_at" in item


def test_unknown_id_returns_404(client):
    response = client.get("/files/no-such-id")
    assert response.status_code == 404


def test_oversize_upload_returns_413(client):
    response = client.post("/files", files={"file": ("big.bin", b"x" * (1024 * 1024 + 1))})
    assert response.status_code == 413


def test_download_returns_identical_bytes(client):
    payload = b"static bytes for the download round-trip test\n" * 10
    file_id = _upload(client, payload, filename="roundtrip.bin",
                      content_type="application/octet-stream")
    response = client.get(f"/files/{file_id}/download")
    assert response.status_code == 200
    assert response.content == payload
    worker.drain_queue()  # clean up this test's own message


def test_delete_removes_s3_object_and_dynamodb_item(client, test_resources):
    file_id = _upload(client, b"to be deleted\n")
    item = client.get(f"/files/{file_id}").json()
    s3_key = item["s3_key"]

    assert client.delete(f"/files/{file_id}").status_code == 204
    assert client.get(f"/files/{file_id}").status_code == 404

    s3, ddb = get_client("s3"), get_client("dynamodb")
    with pytest.raises(botocore.exceptions.ClientError):
        s3.head_object(Bucket=TEST_BUCKET, Key=s3_key)
    assert "Item" not in ddb.get_item(TableName=TEST_TABLE,
                                      Key={"file_id": {"S": file_id}})
    worker.drain_queue()  # clean up this test's own message (poison path)


def test_bootstrap_is_idempotent(test_resources):
    first = bootstrap.ensure_all()
    second = bootstrap.ensure_all()
    assert first == second


def test_worker_reprocessing_is_idempotent(client, test_resources):
    file_id = _upload(client, b"idempotency check\n")
    assert worker.drain_queue()["processed"] == 1
    before = client.get(f"/files/{file_id}").json()
    assert before["status"] == "PROCESSED"

    # Simulate a redelivery of the same message.
    sqs = get_client("sqs")
    queue_url = sqs.get_queue_url(QueueName=TEST_QUEUE)["QueueUrl"]
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps({"file_id": file_id}))
    counts = worker.drain_queue()
    assert counts["processed"] == 0, counts
    assert counts["already"] == 1, counts

    after = client.get(f"/files/{file_id}").json()
    assert after == before  # no corruption, processed_at untouched


def test_worker_marks_failed_on_missing_object(client, test_resources):
    ddb, sqs = get_client("dynamodb"), get_client("sqs")
    ddb.put_item(TableName=TEST_TABLE, Item={
        "file_id": {"S": "missing-object"},
        "filename": {"S": "gone.txt"},
        "content_type": {"S": "text/plain"},
        "size_bytes": {"N": "0"},
        "s3_key": {"S": "uploads/missing-object/gone.txt"},
        "status": {"S": "PENDING"},
        "created_at": {"S": "2026-01-01T00:00:00+00:00"},
    })
    queue_url = sqs.get_queue_url(QueueName=TEST_QUEUE)["QueueUrl"]
    sqs.send_message(QueueUrl=queue_url,
                     MessageBody=json.dumps({"file_id": "missing-object"}))

    counts = worker.drain_queue()  # must not raise
    assert counts["failed"] == 1, counts

    item = client.get("/files/missing-object").json()
    assert item["status"] == "FAILED"
    assert "error" in item and item["error"]


def test_all_sdk_traffic_stays_local(test_resources):
    """Prove no request leaves the laptop, despite amazonaws.com queue URLs.

    The emulator hands out queue URLs on a real AWS hostname
    (``https://sqs.us-east-1.amazonaws.com/...``). boto3 still sends the
    request to the client's configured endpoint, so we capture the actual
    HTTP request URL of every call with a ``before-send`` hook and assert
    each one targets the emulator.
    """
    seen_urls: list = []

    def capture(request, **kwargs):
        seen_urls.append(request.url)

    clients = {}
    for service in ("s3", "dynamodb", "sqs", "sts"):
        created = get_client(service)
        assert created.meta.endpoint_url == EXPECTED_ENDPOINT, service
        created.meta.events.register("before-send.*.*", capture)
        clients[service] = created
    s3, ddb, sqs, sts = (clients[s] for s in ("s3", "dynamodb", "sqs", "sts"))

    assert sts.get_caller_identity()["Account"] == EMULATOR_ACCOUNT_ID

    queue_url = sqs.get_queue_url(QueueName=TEST_QUEUE)["QueueUrl"]
    assert "amazonaws.com" in queue_url  # the trap this test guards against
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps({"ping": True}))
    received = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=1)
    for message in received.get("Messages", []):
        if json.loads(message["Body"]).get("ping"):
            sqs.delete_message(QueueUrl=queue_url,
                               ReceiptHandle=message["ReceiptHandle"])

    s3.put_object(Bucket=TEST_BUCKET, Key="locality/probe.txt", Body=b"probe")
    assert s3.get_object(Bucket=TEST_BUCKET, Key="locality/probe.txt")["Body"].read() == b"probe"
    s3.delete_object(Bucket=TEST_BUCKET, Key="locality/probe.txt")

    ddb.put_item(TableName=TEST_TABLE, Item={"file_id": {"S": "locality-probe"}})
    assert ddb.get_item(TableName=TEST_TABLE,
                        Key={"file_id": {"S": "locality-probe"}})["Item"]
    ddb.delete_item(TableName=TEST_TABLE, Key={"file_id": {"S": "locality-probe"}})

    assert seen_urls, "hook captured no requests"
    for url in seen_urls:
        assert url.startswith(EXPECTED_ENDPOINT), url
        assert "amazonaws.com" not in url, url

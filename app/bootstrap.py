"""Idempotent bootstrap: (re)create the S3 bucket, DynamoDB table and SQS queue.

The emulator keeps state in memory only, so everything vanishes when it
stops. Run this after every start. It is safe to run repeatedly: existing
resources are left untouched, and each step waits until the resource is
usable before returning.
"""

import sys
import time

import botocore.exceptions

from .aws import get_client, guard_emulator_account
from .config import get_settings

TABLE_ACTIVE_TIMEOUT_SECONDS = 60
QUEUE_VISIBILITY_TIMEOUT_SECONDS = 30


def _error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def ensure_bucket(bucket_name: str, region: str) -> None:
    s3 = get_client("s3")
    try:
        s3.head_bucket(Bucket=bucket_name)
        print(f"bucket {bucket_name!r} already exists")
        return
    except botocore.exceptions.ClientError as exc:
        if _error_code(exc) not in ("404", "NoSuchBucket", "NotFound"):
            raise
    kwargs: dict = {"Bucket": bucket_name}
    if region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**kwargs)
    s3.head_bucket(Bucket=bucket_name)  # verify usable
    print(f"bucket {bucket_name!r} created")


def ensure_table(table_name: str) -> None:
    ddb = get_client("dynamodb")
    try:
        status = ddb.describe_table(TableName=table_name)["Table"]["TableStatus"]
        if status == "ACTIVE":
            print(f"table {table_name!r} already exists (ACTIVE)")
            return
    except botocore.exceptions.ClientError as exc:
        if _error_code(exc) != "ResourceNotFoundException":
            raise
        ddb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "file_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "file_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"table {table_name!r} created, waiting for ACTIVE...")
    deadline = time.time() + TABLE_ACTIVE_TIMEOUT_SECONDS
    while True:
        status = ddb.describe_table(TableName=table_name)["Table"]["TableStatus"]
        if status == "ACTIVE":
            print(f"table {table_name!r} is ACTIVE")
            return
        if time.time() > deadline:
            raise TimeoutError(
                f"table {table_name!r} did not become ACTIVE within "
                f"{TABLE_ACTIVE_TIMEOUT_SECONDS}s (last status: {status})"
            )
        time.sleep(1)


def ensure_queue(queue_name: str) -> str:
    """Ensure the queue exists; return its URL (looked up at runtime)."""
    sqs = get_client("sqs")
    try:
        url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        print(f"queue {queue_name!r} already exists")
        return url
    except botocore.exceptions.ClientError as exc:
        if _error_code(exc) != "AWS.SimpleQueueService.NonExistentQueue":
            raise
    url = sqs.create_queue(
        QueueName=queue_name,
        Attributes={"VisibilityTimeout": str(QUEUE_VISIBILITY_TIMEOUT_SECONDS)},
    )["QueueUrl"]
    # Verify usable with a fresh lookup.
    verified = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
    assert verified == url, f"queue URL mismatch: {verified} != {url}"
    print(f"queue {queue_name!r} created")
    return url


def ensure_all() -> dict:
    """Run the account guard, then ensure every resource. Returns a summary."""
    account = guard_emulator_account()
    settings = get_settings()
    ensure_bucket(settings.bucket_name, settings.aws_region)
    ensure_table(settings.table_name)
    queue_url = ensure_queue(settings.queue_name)
    return {
        "account": account,
        "bucket": settings.bucket_name,
        "table": settings.table_name,
        "queue": settings.queue_name,
        "queue_url": queue_url,
    }


def main() -> int:
    try:
        summary = ensure_all()
    except Exception as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 1
    print(f"bootstrap ok: account={summary['account']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Background worker: turn SQS messages into processed DynamoDB results.

Long-polls SQS, reads each file from S3, computes size/line/word/SHA-256 via
:func:`app.processing.process_file_content`, and updates the DynamoDB item to
``PROCESSED``. Failures mark the item ``FAILED`` with an error message and
never crash the loop. ``--once`` drains the queue and exits (for tests).
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone

import botocore.exceptions

from .aws import get_client, guard_emulator_account
from .config import get_settings
from .processing import process_file_content

log = logging.getLogger("worker")

#: SQS long-poll wait. Verified against the emulator: an empty receive with
#: WaitTimeSeconds=2 returned after ~2s with no messages (true long polling).
RECEIVE_WAIT_SECONDS = 10
RECEIVE_MAX_MESSAGES = 10

_stop = False


def _request_stop(signum, frame):
    global _stop
    log.info("received signal %s, shutting down", signum)
    _stop = True


def _error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_failed(ddb, table_name: str, file_id: str, error: str) -> None:
    ddb.update_item(
        TableName=table_name,
        Key={"file_id": {"S": file_id}},
        UpdateExpression="SET #s = :failed, #e = :err, failed_at = :now",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":failed": {"S": "FAILED"},
            ":err": {"S": error[:2000]},
            ":now": {"S": _now_iso()},
        },
    )


def process_one_message(sqs, s3, ddb, table_name: str, bucket_name: str,
                        queue_url: str, message: dict) -> str:
    """Process a single SQS message. Returns an outcome label.

    Outcomes: ``processed``, ``already`` (idempotent re-delivery),
    ``failed`` (item marked FAILED), ``poison`` (unusable message, deleted).
    The message is always deleted exactly once on every path, so a poison
    message can never wedge the queue.
    """
    receipt = message["ReceiptHandle"]

    def delete():
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)

    try:
        body = json.loads(message.get("Body", ""))
        file_id = body.get("file_id")
    except (ValueError, AttributeError):
        log.warning("poison message (not JSON), deleting: %.100r", message.get("Body"))
        delete()
        return "poison"
    if not file_id:
        log.warning("poison message (no file_id), deleting: %.100r", message.get("Body"))
        delete()
        return "poison"

    try:
        existing = ddb.get_item(
            TableName=table_name, Key={"file_id": {"S": file_id}}
        ).get("Item")
        if existing is None:
            log.warning("no DynamoDB item for file_id=%s, deleting message", file_id)
            delete()
            return "poison"
        if existing.get("processed_at") or existing.get("status", {}).get("S") == "PROCESSED":
            log.info("file_id=%s already PROCESSED, skipping", file_id)
            delete()
            return "already"

        s3_key = existing["s3_key"]["S"]
        data = s3.get_object(Bucket=bucket_name, Key=s3_key)["Body"].read()
        result = process_file_content(data)
        try:
            ddb.update_item(
                TableName=table_name,
                Key={"file_id": {"S": file_id}},
                UpdateExpression=(
                    "SET #s = :processed, size_bytes = :size, "
                    "line_count = :lines, word_count = :words, "
                    "sha256 = :sha, processed_at = :now"
                ),
                # First success wins: concurrent redeliveries fail here and
                # are treated as already-processed below. Idempotent.
                ConditionExpression="attribute_not_exists(processed_at)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":processed": {"S": "PROCESSED"},
                    ":size": {"N": str(result["size_bytes"])},
                    ":lines": {"N": str(result["line_count"])},
                    ":words": {"N": str(result["word_count"])},
                    ":sha": {"S": result["sha256"]},
                    ":now": {"S": _now_iso()},
                },
            )
        except botocore.exceptions.ClientError as exc:
            if _error_code(exc) == "ConditionalCheckFailedException":
                log.info("file_id=%s won by a concurrent worker, skipping", file_id)
                delete()
                return "already"
            raise
        log.info("file_id=%s PROCESSED (%d bytes)", file_id, result["size_bytes"])
        delete()
        return "processed"
    except Exception as exc:  # never crash the loop on one bad message
        error = f"{type(exc).__name__}: {exc}"
        log.exception("file_id=%s failed: %s", file_id, error)
        try:
            mark_failed(ddb, table_name, file_id, error)
        except Exception:
            log.exception("could not mark file_id=%s FAILED", file_id)
        delete()  # poison-safe: the FAILED status preserves the evidence
        return "failed"


def poll_batch(sqs, queue_url: str) -> list:
    response = sqs.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=RECEIVE_MAX_MESSAGES,
        WaitTimeSeconds=RECEIVE_WAIT_SECONDS,
        AttributeNames=["ApproximateReceiveCount"],
    )
    return response.get("Messages", [])


def drain_queue(max_batches: int = 1000) -> dict:
    """Receive and process until a poll returns no messages. Returns counts."""
    settings = get_settings()
    sqs, s3, ddb = get_client("sqs"), get_client("s3"), get_client("dynamodb")
    queue_url = sqs.get_queue_url(QueueName=settings.queue_name)["QueueUrl"]
    counts: dict = {"processed": 0, "already": 0, "failed": 0, "poison": 0}
    for _ in range(max_batches):
        if _stop:
            break
        messages = poll_batch(sqs, queue_url)
        if not messages:
            break
        for message in messages:
            outcome = process_one_message(
                sqs, s3, ddb, settings.table_name, settings.bucket_name,
                queue_url, message,
            )
            counts[outcome] += 1
    return counts


def run_loop(poll_interval_seconds: float = 0.0) -> None:
    """Poll forever until SIGINT/SIGTERM."""
    counts = {"processed": 0, "already": 0, "failed": 0, "poison": 0}
    while not _stop:
        batch = drain_queue(max_batches=1)
        for key in counts:
            counts[key] += batch[key]
        if sum(batch.values()) == 0 and poll_interval_seconds > 0 and not _stop:
            time.sleep(poll_interval_seconds)
    log.info("worker stopped: %s", counts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="file pipeline worker")
    parser.add_argument("--once", action="store_true",
                        help="drain the queue and exit (for tests)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        guard_emulator_account()
    except Exception as exc:
        print(f"worker refuses to start: {exc}", file=sys.stderr)
        return 2
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    if args.once:
        counts = drain_queue()
        print(f"worker --once done: {counts}")
    else:
        log.info("worker started (Ctrl-C to stop)")
        run_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

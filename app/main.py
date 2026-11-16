"""REST API: upload files to S3 + DynamoDB + SQS, query status and results."""

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import botocore.exceptions
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .aws import check_emulator, get_client, guard_emulator_account
from .config import MAX_UPLOAD_BYTES, get_settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plain(value: dict):
    """Convert one DynamoDB-JSON attribute value to a plain Python value."""
    if "S" in value:
        return value["S"]
    if "N" in value:
        number = value["N"]
        return int(number) if number.isdigit() else float(number)
    if "BOOL" in value:
        return value["BOOL"]
    if value.get("NULL"):
        return None
    if "L" in value:
        return [_plain(v) for v in value["L"]]
    if "M" in value:
        return {k: _plain(v) for k, v in value["M"].items()}
    raise ValueError(f"unsupported DynamoDB type: {value!r}")


def plain_item(item: dict) -> dict:
    return {key: _plain(value) for key, value in item.items()}


def _error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def _get_item_or_404(table, file_id: str) -> dict:
    response = table.get_item(
        TableName=get_settings().table_name, Key={"file_id": {"S": file_id}}
    )
    item = response.get("Item")
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown file_id: {file_id}")
    return item


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start against anything but the emulator (unless overridden).
    guard_emulator_account()
    yield


app = FastAPI(title="emulator-file-pipeline-poc", lifespan=lifespan)

# The React dev server (frontend/, :5173) calls this API cross-origin.
# Wide open is deliberate for a local PoC; restrict allow_origins before any
# real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    reachable, account = check_emulator()
    settings = get_settings()
    return {
        "status": "ok",
        "emulator_reachable": reachable,
        "account_id": account,
        "region": settings.aws_region,
        "resources": {
            "bucket": settings.bucket_name,
            "table": settings.table_name,
            "queue": settings.queue_name,
        },
    }


@app.post("/files", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    settings = get_settings()
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file too large: {len(content)} bytes "
            f"(limit {MAX_UPLOAD_BYTES} bytes)",
        )
    filename = os.path.basename(file.filename or "") or "upload.bin"
    content_type = file.content_type or "application/octet-stream"
    file_id = uuid.uuid4().hex
    s3_key = f"uploads/{file_id}/{filename}"

    s3 = get_client("s3")
    s3.put_object(
        Bucket=settings.bucket_name,
        Key=s3_key,
        Body=content,
        ContentType=content_type,
    )

    ddb = get_client("dynamodb")
    ddb.put_item(
        TableName=settings.table_name,
        Item={
            "file_id": {"S": file_id},
            "filename": {"S": filename},
            "content_type": {"S": content_type},
            "size_bytes": {"N": str(len(content))},
            "s3_key": {"S": s3_key},
            "status": {"S": "PENDING"},
            "created_at": {"S": _now_iso()},
        },
    )

    sqs = get_client("sqs")
    queue_url = sqs.get_queue_url(QueueName=settings.queue_name)["QueueUrl"]
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps({"file_id": file_id}))

    return {"file_id": file_id, "status": "PENDING"}


@app.get("/files")
def list_files():
    ddb = get_client("dynamodb")
    response = ddb.scan(TableName=get_settings().table_name)
    return [plain_item(item) for item in response.get("Items", [])]


@app.get("/files/{file_id}")
def get_file(file_id: str):
    ddb = get_client("dynamodb")
    return JSONResponse(plain_item(_get_item_or_404(ddb, file_id)))


@app.get("/files/{file_id}/download")
def download_file(file_id: str):
    settings = get_settings()
    ddb = get_client("dynamodb")
    item = plain_item(_get_item_or_404(ddb, file_id))
    s3 = get_client("s3")
    try:
        obj = s3.get_object(Bucket=settings.bucket_name, Key=item["s3_key"])
    except botocore.exceptions.ClientError as exc:
        if _error_code(exc) in ("NoSuchKey", "NoSuchBucket", "404", "NotFound"):
            raise HTTPException(status_code=404, detail="object not found in S3")
        raise
    return StreamingResponse(
        obj["Body"].iter_chunks(),
        media_type=item.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{item["filename"]}"'},
    )


@app.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: str):
    settings = get_settings()
    ddb = get_client("dynamodb")
    item = plain_item(_get_item_or_404(ddb, file_id))
    s3 = get_client("s3")
    try:
        s3.delete_object(Bucket=settings.bucket_name, Key=item["s3_key"])
    except botocore.exceptions.ClientError as exc:
        if _error_code(exc) not in ("NoSuchKey", "NoSuchBucket", "404", "NotFound"):
            raise
    ddb.delete_item(
        TableName=settings.table_name, Key={"file_id": {"S": file_id}}
    )
    return None

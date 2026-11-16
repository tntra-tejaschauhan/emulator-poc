"""Configuration: everything comes from environment variables with sane defaults.

The AWS endpoint, credentials and CA bundle are NOT configured here. They come
from the standard AWS environment (``AWS_ENDPOINT_URL``, ``AWS_CONFIG_FILE``,
``AWS_SHARED_CREDENTIALS_FILE``, ``AWS_CA_BUNDLE`` ...) which boto3 reads
itself, so application code never hardcodes an endpoint URL or credentials.
See ``scripts/env.sh``.
"""

import os
from dataclasses import dataclass

#: Hard safety cap for uploads. The emulator is in-memory; keep payloads small.
MAX_UPLOAD_BYTES = 1024 * 1024  # 1 MiB

#: Account id of the local emulator. The app and worker refuse to start against
#: any other account unless ALLOW_REAL_AWS=1 is set.
EMULATOR_ACCOUNT_ID = "000000000000"


@dataclass(frozen=True)
class Settings:
    bucket_name: str = "poc-files"
    table_name: str = "poc-files"
    queue_name: str = "poc-file-jobs"
    allow_real_aws: bool = False
    api_port: int = 8000
    aws_region: str = "us-east-1"


def get_settings() -> Settings:
    """Read settings from the environment (fresh on every call).

    Reading the environment on each call (instead of caching at import time)
    keeps tests hermetic: they can point the app at their own resource names
    with ``monkeypatch.setenv``.
    """
    return Settings(
        bucket_name=os.environ.get("BUCKET_NAME", "poc-files"),
        table_name=os.environ.get("TABLE_NAME", "poc-files"),
        queue_name=os.environ.get("QUEUE_NAME", "poc-file-jobs"),
        allow_real_aws=os.environ.get("ALLOW_REAL_AWS", "0") == "1",
        api_port=int(os.environ.get("API_PORT", "8000")),
        aws_region=os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1",
    )

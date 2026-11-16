"""AWS client factory plus the emulator account safety guard.

No endpoint URL or credentials are hardcoded here. boto3 resolves both from
the environment: ``AWS_ENDPOINT_URL`` (plus the ``endpoint_url`` baked into
the emulator-generated config file), ``AWS_SHARED_CREDENTIALS_FILE``,
``AWS_CONFIG_FILE`` and ``AWS_CA_BUNDLE``. See ``scripts/env.sh``.
"""

import boto3

from .config import EMULATOR_ACCOUNT_ID, get_settings


def get_client(service: str):
    """Create a boto3 client for the configured region.

    A fresh client is created on every call so tests can repoint the app via
    environment variables at any time. Only the region is passed explicitly;
    endpoint and credentials come from the AWS environment.
    """
    return boto3.client(service, region_name=get_settings().aws_region)


def get_caller_account() -> str:
    """Return the AWS account id behind the current credentials."""
    sts = get_client("sts")
    return sts.get_caller_identity()["Account"]


def check_emulator() -> tuple[bool, str | None]:
    """Check emulator reachability via STS (no hardcoded URL needed).

    Returns ``(reachable, account_id)``; ``account_id`` is None when the
    emulator cannot be reached.
    """
    try:
        return True, get_caller_account()
    except Exception:
        return False, None


class NotEmulatorError(RuntimeError):
    """Raised when the app would talk to something other than the emulator."""


def guard_emulator_account() -> str:
    """Refuse to run against anything but the emulator account.

    Returns the account id when it is the emulator's (``000000000000``) or
    when ``ALLOW_REAL_AWS=1`` is set. Otherwise raises :class:`NotEmulatorError`
    with a clear message. This protects the machine's real AWS credentials
    (``~/.aws/credentials``) from ever being used by accident.
    """
    account = get_caller_account()
    if account == EMULATOR_ACCOUNT_ID or get_settings().allow_real_aws:
        return account
    raise NotEmulatorError(
        f"Refusing to run: AWS account is {account}, not the AWS Emulator "
        f"account ({EMULATOR_ACCOUNT_ID}). Source scripts/env.sh to point the "
        f"AWS environment at the emulator, or set ALLOW_REAL_AWS=1 to "
        f"override (real AWS charges may apply)."
    )

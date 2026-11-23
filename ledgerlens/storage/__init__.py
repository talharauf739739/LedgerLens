"""Azure-compatible storage (Blob, Queue, Key Vault).

The same official SDKs talk to Floci-az locally and real Azure in the cloud.
Only the endpoint and credential change:

- local: ``AZURE_STORAGE_CONNECTION_STRING`` pointing at Floci (port 4577)
- cloud: ``AZURE_STORAGE_ACCOUNT_URL`` + ``DefaultAzureCredential`` (managed identity)
"""

from __future__ import annotations

from azure.core.credentials_async import AsyncTokenCredential
from azure.storage.blob.aio import BlobServiceClient
from azure.storage.queue import TextBase64DecodePolicy, TextBase64EncodePolicy
from azure.storage.queue.aio import QueueClient, QueueServiceClient

from ledgerlens.config import Settings


def _credential() -> AsyncTokenCredential:
    # Async clients need the async credential (azure.identity.aio), not the sync one.
    from azure.identity.aio import DefaultAzureCredential

    return DefaultAzureCredential()


def _queue_account_url(blob_account_url: str) -> str:
    return blob_account_url.replace(".blob.", ".queue.")


def blob_service(settings: Settings) -> BlobServiceClient:
    if settings.azure_storage_connection_string:
        return BlobServiceClient.from_connection_string(
            settings.azure_storage_connection_string.get_secret_value()
        )
    if settings.azure_storage_account_url:
        return BlobServiceClient(settings.azure_storage_account_url, credential=_credential())
    raise ValueError("Set AZURE_STORAGE_CONNECTION_STRING (local) or AZURE_STORAGE_ACCOUNT_URL")


def queue_service(settings: Settings) -> QueueServiceClient:
    if settings.azure_storage_connection_string:
        return QueueServiceClient.from_connection_string(
            settings.azure_storage_connection_string.get_secret_value()
        )
    if settings.azure_storage_account_url:
        return QueueServiceClient(
            _queue_account_url(settings.azure_storage_account_url),
            credential=_credential(),
        )
    raise ValueError("Set AZURE_STORAGE_CONNECTION_STRING (local) or AZURE_STORAGE_ACCOUNT_URL")


def jobs_queue(settings: Settings) -> QueueClient:
    """The extraction-jobs queue. Messages are base64 JSON, matching Azure Functions' default.

    Built directly (not via a QueueServiceClient) so the returned client owns, and closes,
    its own HTTP session.
    """
    if settings.azure_storage_connection_string:
        return QueueClient.from_connection_string(
            settings.azure_storage_connection_string.get_secret_value(),
            settings.jobs_queue,
            message_encode_policy=TextBase64EncodePolicy(),
            message_decode_policy=TextBase64DecodePolicy(),
        )
    if settings.azure_storage_account_url:
        return QueueClient(
            _queue_account_url(settings.azure_storage_account_url),
            settings.jobs_queue,
            credential=_credential(),
            message_encode_policy=TextBase64EncodePolicy(),
            message_decode_policy=TextBase64DecodePolicy(),
        )
    raise ValueError("Set AZURE_STORAGE_CONNECTION_STRING (local) or AZURE_STORAGE_ACCOUNT_URL")


async def ensure_resources(settings: Settings) -> None:
    """Create the blob container and jobs queue if missing (idempotent; used at startup)."""
    from azure.core.exceptions import ResourceExistsError

    async with blob_service(settings) as blobs:
        try:
            await blobs.create_container(settings.blob_container)
        except ResourceExistsError:
            pass
    async with jobs_queue(settings) as queue:
        try:
            await queue.create_queue()
        except ResourceExistsError:
            pass

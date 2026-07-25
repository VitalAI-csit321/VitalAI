"""Thin MinIO (S3-compatible) wrapper for clinical document bytes.

boto3 is synchronous; callers on the async request path should wrap calls
in asyncio.to_thread rather than call these directly (see
app/services/clinical_document_service.py).
"""

from __future__ import annotations

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings


def _get_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(s3={"addressing_style": "path"}),
    )


def _ensure_bucket(client) -> None:
    try:
        client.head_bucket(Bucket=settings.minio_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.minio_bucket)


def put_object(key: str, data: bytes, content_type: str) -> None:
    client = _get_client()
    _ensure_bucket(client)
    client.put_object(Bucket=settings.minio_bucket, Key=key, Body=data, ContentType=content_type)


def get_object(key: str) -> bytes:
    client = _get_client()
    response = client.get_object(Bucket=settings.minio_bucket, Key=key)
    body: bytes = response["Body"].read()
    return body

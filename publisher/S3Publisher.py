from __future__ import annotations

import json
import os

import boto3

from .Publisher import Publisher


class S3Publisher(Publisher):
    """Publishes data to an S3 bucket."""

    def __init__(self, bucket: str | None = None, prefix: str = ""):
        self._bucket = bucket or os.environ["S3_BUCKET_NAME"]
        self._prefix = prefix
        self._s3 = boto3.client(
            "s3",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )

    def _full_key(self, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{key}"
        return key

    def publish(self, key: str, data: bytes) -> None:
        self._s3.put_object(
            Bucket=self._bucket,
            Key=self._full_key(key),
            Body=data,
        )

    def publish_json(self, key: str, obj: dict) -> None:
        self.publish(key, json.dumps(obj).encode("utf-8"))

    def get(self, key: str) -> bytes:
        resp = self._s3.get_object(
            Bucket=self._bucket,
            Key=self._full_key(key),
        )
        return resp["Body"].read()

    def delete(self, key: str) -> None:
        self._s3.delete_object(
            Bucket=self._bucket,
            Key=self._full_key(key),
        )

    def list_keys(self, prefix: str = "") -> list[str]:
        full_prefix = self._full_key(prefix)
        resp = self._s3.list_objects_v2(
            Bucket=self._bucket,
            Prefix=full_prefix,
        )
        return [obj["Key"] for obj in resp.get("Contents", [])]

import os

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


class S3Storage:
    def __init__(self):
        self.access_key = os.getenv("STORAGE_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
        self.secret_key = os.getenv("STORAGE_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
        self.region = os.getenv("STORAGE_REGION") or os.getenv("AWS_REGION")
        self.bucket = os.getenv("STORAGE_BUCKET_NAME") or os.getenv("AWS_STORAGE_BUCKET_NAME")
        endpoint = os.getenv("STORAGE_ENDPOINT_URL")
        if not endpoint and self.region:
            endpoint = f"https://s3.{self.region}.backblazeb2.com"
        self._client = boto3.client(
            "s3",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            endpoint_url=endpoint,
            config=Config(signature_version="s3v4"),
        )
        self._public_base = os.getenv(
            "STORAGE_PUBLIC_URL_BASE",
            f"https://{self.bucket}.s3.{self.region}.backblazeb2.com",
        )

    def upload(self, key: str, body: bytes, content_type: str) -> str:
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType=content_type
        )
        return f"{self._public_base}/{key}"

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

"""
Quick integration tests for S3Publisher.

Usage:
    python -m publisher.tests.test_s3_publisher          # run write/read tests
    python -m publisher.tests.test_s3_publisher --clean   # delete all test objects
"""

import json
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from publisher import S3Publisher

TEST_PREFIX = "botvader-tests"


def get_publisher() -> S3Publisher:
    return S3Publisher(prefix=TEST_PREFIX)


def test_publish_bytes():
    pub = get_publisher()
    key = f"bytes-{int(time.time())}.txt"
    data = b"hello from botvader"

    pub.publish(key, data)
    result = pub.get(key)

    assert result == data, f"Expected {data!r}, got {result!r}"
    print(f"  PASS  publish/get bytes  ({key})")


def test_publish_json():
    pub = get_publisher()
    key = f"json-{int(time.time())}.json"
    obj = {"feed": "test", "ts": time.time(), "values": [1, 2, 3]}

    pub.publish_json(key, obj)
    result = json.loads(pub.get(key))

    assert result == obj, f"Expected {obj!r}, got {result!r}"
    print(f"  PASS  publish/get json   ({key})")


def test_list_keys():
    pub = get_publisher()
    keys = pub.list_keys()

    assert len(keys) > 0, "Expected at least one key after previous tests"
    print(f"  PASS  list_keys          ({len(keys)} keys found)")


def test_delete():
    pub = get_publisher()
    key = f"delete-me-{int(time.time())}.txt"

    pub.publish(key, b"temporary")
    pub.delete(key)

    remaining = pub.list_keys(prefix="delete-me-")
    assert not any(key in k for k in remaining), f"Key {key} still exists after delete"
    print(f"  PASS  delete             ({key})")


def clean():
    """Remove all objects under the test prefix."""
    pub = get_publisher()
    keys = pub.list_keys()

    if not keys:
        print("Nothing to clean.")
        return

    for key in keys:
        # keys come back with full prefix already
        pub._s3.delete_object(Bucket=pub._bucket, Key=key)
        print(f"  DELETED  {key}")

    print(f"\nCleaned {len(keys)} test objects.")


if __name__ == "__main__":
    if "--clean" in sys.argv:
        print("Cleaning test objects...\n")
        clean()
    else:
        print("Running S3Publisher tests...\n")
        test_publish_bytes()
        test_publish_json()
        test_list_keys()
        test_delete()
        print("\nAll tests passed.")

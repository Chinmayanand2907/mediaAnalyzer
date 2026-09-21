#!/usr/bin/env python3
"""Verify Celery pipeline health without burning API quota or mutating prod data."""
import argparse
import sys

import redis
from celery.exceptions import TimeoutError

from app.core.celery_app import celery_app
from app.core.config import get_settings

settings = get_settings()

REQUIRED_TASKS = [
    'app.tasks.ingestion_tasks.tasks_ingest_youtube_data',
    'app.tasks.ingestion_tasks.tasks_ingest_reddit_data',
    'app.tasks.ingestion_tasks.task_process_sentiment',
]


def verify_redis():
    print("[1] Checking Redis Broker Connectivity...")
    try:
        r = redis.from_url(settings.CELERY_BROKER_URL)
        if r.ping():
            print("✅ Redis is alive and responding to pings.")
            return True
        print("❌ Redis ping failed.")
        return False
    except Exception as e:
        print(f"❌ Redis connection error: {e}")
        return False


def verify_worker_liveliness():
    print("\n[2] Checking Worker Liveliness...")
    try:
        i = celery_app.control.inspect()
        active = i.active()
        if active:
            print(f"✅ Found active worker(s): {list(active.keys())}")
            return True
        print("❌ No active Celery workers found. Run: celery -A app.core.celery_app worker --loglevel=info -Q celery,youtube,reddit")
        return False
    except Exception as e:
        print(f"❌ Error inspecting workers: {e}")
        return False


def verify_task_registration():
    print("\n[3] Checking Task Registration...")
    try:
        i = celery_app.control.inspect()
        registered_tasks = i.registered()
        if not registered_tasks:
            print("❌ Could not fetch registered tasks. Worker might be down.")
            return False

        all_tasks = set()
        for worker_tasks in registered_tasks.values():
            all_tasks.update(worker_tasks)

        missing = [t for t in REQUIRED_TASKS if t not in all_tasks]
        if missing:
            print(f"❌ Missing tasks in registry: {missing}")
            print(f"   Found tasks: {all_tasks}")
            return False

        print("✅ All required tasks are successfully registered.")
        return True
    except Exception as e:
        print(f"❌ Error checking task registry: {e}")
        return False


def verify_mock_execution(execute: bool, timeout: int):
    print("\n[4] Task Execution Check...")
    if not execute:
        print("   Skipped (pass --execute to dispatch a real task; costs YouTube quota).")
        return True
    try:
        print("   Dispatching via canonical celery_app.send_task (no quota-free mock)...")
        result = celery_app.send_task(
            'app.tasks.ingestion_tasks.tasks_ingest_youtube_data',
            args=["UCeVMnSShP_Iviwkknt83cww"],
        )
        print(f"   Task dispatched with ID: {result.id}")
        print(f"   Waiting for task resolution (timeout={timeout}s)...")
        output = result.get(timeout=timeout)
        print(f"✅ Task executed successfully. Result: {output}")
        return True
    except TimeoutError:
        print(f"❌ Task execution timed out after {timeout} seconds.")
        return False
    except Exception as e:
        print(f"❌ Task execution failed with error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Verify Celery pipeline health")
    parser.add_argument("--execute", action="store_true", help="Actually dispatch a real ingestion task (costs quota)")
    parser.add_argument("--timeout", type=int, default=120, help="Task wait timeout in seconds")
    args = parser.parse_args()

    print("=== CELERY PIPELINE VERIFICATION ===\n")

    redis_ok = verify_redis()
    worker_ok = verify_worker_liveliness()
    registry_ok = verify_task_registration()
    exec_ok = verify_mock_execution(args.execute, args.timeout) if worker_ok else False
    if not worker_ok:
        print("\n[4] Skipping execution because worker is not online.")

    print("\n=== SUMMARY ===")
    if redis_ok and worker_ok and registry_ok and exec_ok:
        print("🎉 ALL CHECKS PASSED! Background pipeline is healthy.")
        sys.exit(0)
    else:
        print("⚠️ SOME CHECKS FAILED. Please check the logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

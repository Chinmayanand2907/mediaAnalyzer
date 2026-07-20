import sys
import redis
from celery.exceptions import TimeoutError
from app.core.config import get_settings
from app.tasks.celery_app import celery_app
from app.tasks.ingestion_tasks import tasks_ingest_youtube_data, tasks_ingest_reddit_data

settings = get_settings()

def verify_redis():
    print("[1] Checking Redis Broker Connectivity...")
    try:
        r = redis.from_url(settings.CELERY_BROKER_URL)
        ping_result = r.ping()
        if ping_result:
            print("✅ Redis is alive and responding to pings.")
        else:
            print("❌ Redis ping failed.")
            return False
    except Exception as e:
        print(f"❌ Redis connection error: {e}")
        return False
    return True

def verify_worker_liveliness():
    print("\n[2] Checking Worker Liveliness...")
    try:
        i = celery_app.control.inspect()
        active = i.active()
        if active:
            print(f"✅ Found active worker(s): {list(active.keys())}")
            return True
        else:
            print("❌ No active Celery workers found. Are you running 'celery -A app.tasks.celery_app worker'?")
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
            
        required_tasks = [
            'app.tasks.ingestion_tasks.tasks_ingest_youtube_data',
            'app.tasks.ingestion_tasks.tasks_ingest_reddit_data'
        ]
        
        missing = [t for t in required_tasks if t not in all_tasks]
        if missing:
            print(f"❌ Missing tasks in registry: {missing}")
            print(f"   Found tasks: {all_tasks}")
            return False
            
        print("✅ All required tasks are successfully registered.")
        return True
    except Exception as e:
        print(f"❌ Error checking task registry: {e}")
        return False

def verify_mock_execution():
    print("\n[4] Executing Mock Task End-to-End...")
    try:
        channel_id = "UC_mock_channel_id"
        print(f"   Dispatching tasks_ingest_youtube_data for '{channel_id}'...")
        # Dispatch the task
        result = tasks_ingest_youtube_data.delay(channel_id)
        print(f"   Task dispatched with ID: {result.id}")
        print("   Waiting for task resolution (timeout=10s)...")
        
        # Await resolution
        output = result.get(timeout=10)
        print(f"✅ Task executed successfully. Result: {output}")
        return True
    except TimeoutError:
        print("❌ Task execution timed out after 10 seconds.")
        return False
    except Exception as e:
        print(f"❌ Task execution failed with error: {e}")
        return False

def main():
    print("=== CELERY PIPELINE VERIFICATION ===\n")
    
    redis_ok = verify_redis()
    worker_ok = verify_worker_liveliness()
    registry_ok = verify_task_registration()
    
    if worker_ok:
        exec_ok = verify_mock_execution()
    else:
        print("\n[4] Skipping Mock Execution because worker is not online.")
        exec_ok = False
        
    print("\n=== SUMMARY ===")
    if redis_ok and worker_ok and registry_ok and exec_ok:
        print("🎉 ALL TESTS PASSED! Background pipeline is healthy.")
        sys.exit(0)
    else:
        print("⚠️ SOME TESTS FAILED. Please check the logs above.")
        sys.exit(1)

if __name__ == "__main__":
    main()

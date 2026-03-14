from google.cloud import firestore
import subprocess
import math

db = firestore.Client()

MAX_WORKERS = 10
JOBS_PER_WORKER = 4


def get_queue_size():

    query = (
        db.collection("jobs")
        .where("status", "==", "queued")
        .count()
    )

    result = query.get()

    return result[0][0].value


def calculate_workers(queue_size):

    workers = math.ceil(queue_size / JOBS_PER_WORKER)

    return min(workers, MAX_WORKERS)


def launch_workers(worker_count):

    if worker_count == 0:
        print("Queue empty")
        return

    print(f"Launching {worker_count} workers")

    subprocess.run(
        [
            "gcloud",
            "run",
            "jobs",
            "execute",
            "kreyai-worker",
            "--tasks",
            str(worker_count),
            "--region",
            "us-central1",
        ],
        check=True,
    )


def autoscale():

    queue_size = get_queue_size()

    print("Queued jobs:", queue_size)

    workers = calculate_workers(queue_size)

    launch_workers(workers)
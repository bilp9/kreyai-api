from app.queueing.queue import LocalSQLiteQueue

_queue = LocalSQLiteQueue()

def get_queue():
    return _queue

"""Bounded, process-local caches. Never persist private planning states to disk."""
from collections import Counter, OrderedDict
import json
import threading
from functools import wraps


def synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock: return method(self, *args, **kwargs)
    return call


class PlanningCache:
    def __init__(self, max_bytes=48 * 1024 * 1024, max_entries=1200):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.entries = OrderedDict()
        self.bytes = 0
        self.stats = Counter()
        self.lock = threading.RLock()

    @synchronized
    def get(self, kind, sid, key):
        identity = (kind, sid, key)
        entry = self.entries.get(identity)
        if entry is None:
            self.stats[kind + '_misses'] += 1
            return None
        self.entries.move_to_end(identity)
        self.stats[kind + '_hits'] += 1
        return json.loads(entry[0])

    @synchronized
    def put(self, kind, sid, key, value):
        identity = (kind, sid, key)
        payload = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        size = len(payload)
        if size > self.max_bytes: return
        previous = self.entries.pop(identity, None)
        if previous: self.bytes -= previous[1]
        self.entries[identity] = (payload, size)
        self.bytes += size
        while self.bytes > self.max_bytes or len(self.entries) > self.max_entries:
            self.bytes -= self.entries.popitem(last=False)[1][1]

    @synchronized
    def discard(self, sid, kind=None):
        for identity in list(self.entries):
            if identity[1] == sid and (kind is None or identity[0] == kind):
                self.bytes -= self.entries.pop(identity)[1]

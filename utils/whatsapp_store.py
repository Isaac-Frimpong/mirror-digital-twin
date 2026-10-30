"""Small per-sender store. Memory for testing, optional Redis with expiry."""
import hashlib
import hmac
import json
import threading
import time
from contextlib import contextmanager

TTL_SECONDS=24*60*60

def fresh():
    return {'consented':False,'language':'en','events':[],'profile':{},'image_consent':False,'seen':{},'rate':[]}

class Store:
    def __init__(self, secret, redis_url=None):
        self.secret=secret.encode(); self.data={}; self.locks={}; self.guard=threading.Lock()
        self.redis=None
        if redis_url:
            import redis
            self.redis=redis.Redis.from_url(redis_url,decode_responses=True,socket_connect_timeout=3,socket_timeout=3)
            self.redis.ping()  # fail closed, do not quietly use volatile memory
    def key(self,sender):
        return 'mirror:session:'+hmac.new(self.secret,sender.encode(),hashlib.sha256).hexdigest()
    @contextmanager
    def transaction(self,sender):
        key=self.key(sender); now=time.time()
        if self.redis:
            # One sender at a time across workers. Release is handled by Redis lock.
            with self.redis.lock(key+':lock', timeout=90, blocking_timeout=3):
                raw=self.redis.get(key); state=json.loads(raw) if raw else fresh()
                yield state
                self.redis.set(key,json.dumps(state),ex=TTL_SECONDS)
        else:
            with self.guard:
                # Cleanup avoids retaining inactive sessions indefinitely.
                for k in list(self.data):
                    if self.data[k][0] < now: del self.data[k]
                lock=self.locks.setdefault(key,threading.RLock())
            with lock:
                item=self.data.get(key); state=item[1] if item and item[0]>=now else fresh()
                yield state
                self.data[key]=(time.time()+TTL_SECONDS,state)

import json
import threading

from websockets.sync.server import serve


class DataStream:
    """Sends every tracker reading to whoever is connected, as JSON."""

    def __init__(self, host="127.0.0.1", port=8765):
        self.clients = set()
        self.lock = threading.Lock()
        self.server = serve(self._handle, host, port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handle(self, ws):
        with self.lock:
            self.clients.add(ws)
        try:
            for _ in ws:  # we don't expect anything back, just keep it open
                pass
        finally:
            with self.lock:
                self.clients.discard(ws)

    def send(self, data):
        msg = json.dumps(data)
        with self.lock:
            clients = list(self.clients)
        for ws in clients:
            try:
                ws.send(msg)
            except Exception:
                pass  # client went away, _handle will clean it up

    def close(self):
        self.server.shutdown()

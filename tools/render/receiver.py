import http.server, sys
OUT = sys.argv[1]
class H(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "*"); self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
    def do_OPTIONS(self): self.send_response(204); self._cors(); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); data = self.rfile.read(n)
        open(OUT, "wb").write(data); self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b"ok")
        print("received", n, "bytes", flush=True)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", 8735), H).serve_forever()

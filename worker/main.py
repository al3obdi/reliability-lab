import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from consumer import start_consumer
from services.postgres import get_pool, close_pool
from services.elasticsearch import ensure_index, close_client
from metrics import get_metrics


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(get_metrics())
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress HTTP request logging


def _start_metrics_server(port: int = 9100):
    """Start a minimal HTTP server for Prometheus metrics scraping."""
    server = HTTPServer(("0.0.0.0", port), MetricsHandler)
    print(f"[WORKER] Metrics server on :{port}", flush=True)
    server.serve_forever()


async def main():
    # PostgreSQL pool is FATAL — worker cannot function without it
    await get_pool()
    print("[WORKER] PostgreSQL pool ready", flush=True)

    # Elasticsearch is NON-FATAL — derived store, can be rebuilt later
    try:
        await ensure_index()
    except Exception as exc:
        print(f"[WORKER] WARNING: Elasticsearch unavailable ({exc}) — continuing without ES", flush=True)

    # Start metrics server in a separate thread (fire-and-forget)
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _start_metrics_server, 9100)

    connection = await start_consumer()
    try:
        await asyncio.Future()  # run forever
    finally:
        await connection.close()
        await close_pool()
        await close_client()


if __name__ == "__main__":
    asyncio.run(main())

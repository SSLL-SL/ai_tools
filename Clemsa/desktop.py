import threading
import time
import urllib.request
import webview
from app import start_server

FLASK_PORT = 5050
FLASK_URL = f"http://127.0.0.1:{FLASK_PORT}"


def run_flask():
    start_server(host="127.0.0.1", port=FLASK_PORT, debug=False)


def wait_for_server(url, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    if not wait_for_server(FLASK_URL):
        print("Error: Flask server did not start in time")
        exit(1)

    webview.create_window(
        "PS4 FPKG Collection",
        FLASK_URL,
        width=1400,
        height=900,
        resizable=True,
        min_size=(900, 600),
    )
    webview.start()

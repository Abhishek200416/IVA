"""
Ivy 24/7 Autonomous Voice & Chat Daemon
Runs locally on port 8090.
Enables real-time 24/7 conversation with Ivy, synthesized directly into audio using
the user's chosen Serafina voice profile and played out loud through Windows audio.
Serves the System-Wide Floating Voice Call HUD at /call and /.
"""

import os
import sys
import time
import json
import random
import threading
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.parse

from iva_voice_engine import IvaVoiceEngine
from ivy_agent_executor import execute_agent_intent

DAEMON_PORT = 8090
AUDIO_OUTPUT_DIR = Path("scratch/agent_speech")
AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
HUD_HTML_PATH = Path(__file__).parent / "iva_call_hud.html"


GENERATION_LOCK = threading.Lock()
CURRENT_TASK_ID = 0


class IvyVoiceChatHandler(BaseHTTPRequestHandler):
    def _set_headers(self, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # Serve the Desktop Call HUD Interface
        if parsed.path in ["/", "/call", "/hud", "/index.html"]:
            if HUD_HTML_PATH.exists():
                self._set_headers(content_type="text/html; charset=utf-8")
                with open(HUD_HTML_PATH, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "HUD HTML file not found")
            return

        if parsed.path == "/api/status":
            engine = IvaVoiceEngine.get_instance()
            payload = {
                "status": "ONLINE",
                "daemon": "Ivy 24/7 Voice & Chat Guardian",
                "port": DAEMON_PORT,
                "voice_profile": "Serafina - Sensual Temptress (Locked)",
                "sample_rate": engine.model.sr,
                "ref_audio": engine.voice_clip_path,
                "time": time.ctime(),
            }
            self._set_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        # Serve static audio files (both scratch/agent_speech and scratch/voice_cache)
        if parsed.path.startswith("/audio/"):
            filename = Path(parsed.path).name
            file_path = AUDIO_OUTPUT_DIR / filename
            if not file_path.exists():
                file_path = Path("scratch/voice_cache") / filename
            if file_path.exists():
                self._set_headers(content_type="audio/wav")
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "Audio file not found")
            return

        self.send_error(404, "Endpoint not found")

    def do_POST(self):
        global CURRENT_TASK_ID
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ["/api/chat", "/chat"]:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            try:
                data = json.loads(raw_body.decode("utf-8"))
            except Exception:
                data = {}

            user_msg = data.get("message", "").strip()

            if not user_msg:
                reply_text = "Hey darling, I'm right here with you!"
                action_meta = {"intent": "GREETING", "cache_key": "greeting_1", "executed": True}
            else:
                reply_text, action_meta = execute_agent_intent(user_msg)

            print(f"[Ivy 24/7 Daemon] User: {user_msg}")
            print(f"[Ivy 24/7 Daemon] Ivy: {reply_text} (Action: {action_meta})")

            # Check instant cache first for zero-latency response!
            cache_key = action_meta.get("cache_key")
            cache_file = Path("scratch/voice_cache") / f"{cache_key}.wav" if cache_key else None

            if cache_file and cache_file.exists():
                audio_filename = f"{cache_key}.wav"
                print(f"[Ivy 24/7 Daemon] Instant cache HIT for '{cache_key}' -> 0.00s latency!")
            else:
                engine = IvaVoiceEngine.get_instance()
                audio_filename = f"ivy_chat_{int(time.time()*1000)}.wav"
                audio_dest = AUDIO_OUTPUT_DIR / audio_filename
                engine.speak(reply_text, output_path=audio_dest, play=False)

            response_payload = {
                "reply": reply_text,
                "action": action_meta,
                "audio_url": f"http://127.0.0.1:{DAEMON_PORT}/audio/{audio_filename}",
                "audio_filename": audio_filename,
                "cached": bool(cache_file and cache_file.exists()),
                "timestamp": time.time(),
            }

            self._set_headers()
            self.wfile.write(json.dumps(response_payload).encode("utf-8"))
            return

        if parsed.path in ["/api/stop", "/stop"]:
            with GENERATION_LOCK:
                CURRENT_TASK_ID += 1
            print(f"[Ivy 24/7 Daemon] Stop signal received. Incremented task ID to {CURRENT_TASK_ID}.")
            self._set_headers()
            self.wfile.write(json.dumps({"status": "STOPPED", "task_id": CURRENT_TASK_ID}).encode("utf-8"))
            return

        if parsed.path in ["/api/speak", "/speak"]:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            try:
                data = json.loads(raw_body.decode("utf-8"))
            except Exception:
                data = {}

            text_to_speak = data.get("text", "Hello my love.").strip()
            
            with GENERATION_LOCK:
                CURRENT_TASK_ID += 1
                my_task_id = CURRENT_TASK_ID

            # Acquire lock to ensure serialized, single-voice execution
            with GENERATION_LOCK:
                if my_task_id != CURRENT_TASK_ID:
                    print(f"[Ivy 24/7 Daemon] Task {my_task_id} preempted by newer task {CURRENT_TASK_ID}. Skipping.")
                    self._set_headers()
                    self.wfile.write(json.dumps({"status": "PREEMPTED"}).encode("utf-8"))
                    return

                engine = IvaVoiceEngine.get_instance()
                audio_filename = f"ivy_speak_{int(time.time()*1000)}.wav"
                audio_dest = AUDIO_OUTPUT_DIR / audio_filename
                engine.speak(text_to_speak, output_path=audio_dest, play=False)

            self._set_headers()
            self.wfile.write(json.dumps({
                "status": "SPOKEN",
                "text": text_to_speak,
                "audio_url": f"http://127.0.0.1:{DAEMON_PORT}/audio/{audio_filename}"
            }).encode("utf-8"))
            return

        self.send_error(404, "Endpoint not found")

    def log_message(self, format, *args):
        # Concise logging
        pass


def run_daemon():
    print(f"=== Starting Ivy 24/7 Voice & Chat Daemon ===")
    print(f"Pre-warming voice engine with Serafina profile...")
    engine = IvaVoiceEngine.get_instance()
    server = ThreadingHTTPServer(("127.0.0.1", DAEMON_PORT), IvyVoiceChatHandler)
    print(f"Ivy 24/7 Daemon is ACTIVE at: http://127.0.0.1:{DAEMON_PORT}")
    print(f"Serving Voice Call HUD at: http://127.0.0.1:{DAEMON_PORT}/call")
    print(f"Ready for continuous microphone and real-time speech!")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down Ivy daemon.")
        server.shutdown()


if __name__ == "__main__":
    run_daemon()

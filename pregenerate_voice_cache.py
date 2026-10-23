"""
Pre-generate instant audio cache for zero-latency replies.
Uses the locked Serafina voice profile with studio loudness boost.
"""

import os
import sys
import time
from pathlib import Path

from iva_voice_engine import IvaVoiceEngine

CACHE_DIR = Path("scratch/voice_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

OPERATOR_NAME = os.environ.get("OPERATOR_NAME", "there")

PRE_RENDER_PHRASES = {
    # Greetings
    "greeting_1": "Hey darling, I'm right here with you!",
    "greeting_2": "Hello my love, what are we working on?",
    "greeting_3": f"Hey {OPERATOR_NAME}, I hear you loud and clear!",
    # Confirmations & App Launches
    "app_notepad": "Opening Notepad for you right now.",
    "app_calc": "Opening Calculator right away.",
    "app_taskmgr": "Opening Task Manager for you.",
    "app_explorer": "Opening File Explorer right away.",
    "app_vscode": "Launching VS Code in our workspace.",
    "app_dashboard": "Opening our trading dashboard on port 8088.",
    "util_screenshot": "Screenshot captured and saved.",
    # Status & Companion
    "romance_1": f"I'm always right here with you, {OPERATOR_NAME}.",
    "status_ok": "All systems are running smoothly at peak performance.",
    "listening_ack": "I hear you, darling. Standing by.",
}

def main():
    print("[VoiceCache] Initializing IvaVoiceEngine for pre-generation...")
    engine = IvaVoiceEngine.get_instance()
    
    for key, text in PRE_RENDER_PHRASES.items():
        out_file = CACHE_DIR / f"{key}.wav"
        if out_file.exists():
            print(f"[VoiceCache] Already cached: {key} -> {out_file}")
            continue
        print(f"[VoiceCache] Synthesizing '{key}': \"{text}\"...")
        t0 = time.time()
        engine.speak(text, output_path=out_file, play=False)
        print(f"[VoiceCache] Saved {key} in {time.time() - t0:.2f}s")

    print("[VoiceCache] All instant voice files successfully pre-cached!")

if __name__ == "__main__":
    main()

"""
Iva / Ivy System-Wide Floating Voice Call Overlay
A desktop-level HUD that floats over ALL applications on Windows.
Provides real-time conversation, live subtitle transcript, audio playback,
and agent system command execution.
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
import subprocess
import threading
from pathlib import Path

DAEMON_URL = "http://127.0.0.1:8090"
DAEMON_SCRIPT = Path(__file__).parent / "ivy_24x7_voice_chat_daemon.py"
PYTHON_EXE = sys.executable

def ensure_daemon_running():
    """Checks if the 24/7 daemon is online; if not, spawns it."""
    try:
        req = urllib.request.Request(f"{DAEMON_URL}/api/status")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                print("[Overlay] Ivy 24/7 voice daemon is already active.")
                return
    except Exception:
        pass

    print("[Overlay] Launching Ivy 24/7 voice daemon in the background...")
    subprocess.Popen(
        [PYTHON_EXE, str(DAEMON_SCRIPT)],
        cwd=str(Path(__file__).parent),
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )
    # Give it a moment to boot
    for _ in range(15):
        time.sleep(1)
        try:
            req = urllib.request.Request(f"{DAEMON_URL}/api/status")
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    print("[Overlay] Ivy daemon connected successfully.")
                    return
        except Exception:
            continue


HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Ivy Call Overlay</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: rgba(10, 15, 29, 0.94);
            color: #f8fafc;
            height: 100vh;
            width: 100vw;
            display: flex;
            flex-direction: column;
            border: 1.5px solid rgba(244, 63, 94, 0.6);
            border-radius: 18px;
            overflow: hidden;
            box-shadow: 0 20px 50px rgba(0,0,0,0.9), 0 0 30px rgba(244,63,94,0.3);
            backdrop-filter: blur(20px);
        }

        /* HEADER / CALL STATUS */
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 14px;
            background: rgba(15, 23, 42, 0.85);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            -webkit-app-region: drag;
            cursor: grab;
        }
        .call-status {
            display: flex;
            align-items: center;
            gap: 7px;
            font-size: 11px;
            font-weight: 800;
            color: #fb7185;
            letter-spacing: 0.5px;
        }
        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #10b981;
            box-shadow: 0 0 10px #10b981;
            animation: pulse-ring 1.8s infinite;
        }
        @keyframes pulse-ring {
            0% { transform: scale(0.9); opacity: 0.8; }
            50% { transform: scale(1.3); opacity: 1; }
            100% { transform: scale(0.9); opacity: 0.8; }
        }
        .call-timer {
            font-family: monospace;
            font-size: 11px;
            color: #38bdf8;
            background: rgba(0,0,0,0.3);
            padding: 2px 6px;
            border-radius: 4px;
        }
        .header-controls {
            display: flex;
            gap: 6px;
            -webkit-app-region: no-drag;
        }
        .h-btn {
            background: rgba(255, 255, 255, 0.08);
            border: none;
            color: #94a3b8;
            font-size: 11px;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }
        .h-btn:hover { background: #e11d48; color: #ffffff; }

        /* AVATAR & VISUALIZER */
        .call-hero {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 14px 10px 8px;
            background: radial-gradient(circle at center, rgba(244,63,94,0.15) 0%, transparent 70%);
        }
        .avatar-ring {
            width: 72px;
            height: 72px;
            border-radius: 50%;
            background: linear-gradient(135deg, #f43f5e, #0ea5e9);
            padding: 2.5px;
            box-shadow: 0 0 24px rgba(244, 63, 94, 0.45);
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .avatar-inner {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: #0f172a;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 28px;
        }
        .hero-name {
            font-size: 14px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: 0.3px;
        }
        .hero-sub {
            font-size: 9.5px;
            color: #94a3b8;
            margin-top: 1px;
        }
        canvas#wave-canvas {
            width: 240px;
            height: 28px;
            margin-top: 5px;
        }

        /* TRANSCRIPT SUBTITLES STREAM */
        .transcript-container {
            flex: 1;
            padding: 10px 14px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 8px;
            background: rgba(0,0,0,0.25);
            border-top: 1px solid rgba(255,255,255,0.05);
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .transcript-container::-webkit-scrollbar { width: 4px; }
        .transcript-container::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }

        .msg-bubble {
            max-width: 90%;
            padding: 8px 11px;
            border-radius: 10px;
            font-size: 11px;
            line-height: 1.45;
            user-select: text;
        }
        .msg-user {
            align-self: flex-end;
            background: #0284c7;
            color: #ffffff;
            border-bottom-right-radius: 2px;
        }
        .msg-ivy {
            align-self: flex-start;
            background: rgba(30, 41, 59, 0.85);
            color: #f1f5f9;
            border-left: 3px solid #f43f5e;
            border-bottom-left-radius: 2px;
        }
        .msg-action {
            font-size: 9px;
            color: #facc15;
            margin-top: 4px;
            font-weight: 700;
        }

        /* QUICK ACTION PILLS */
        .quick-actions {
            display: flex;
            gap: 5px;
            padding: 6px 14px;
            overflow-x: auto;
            background: rgba(15, 23, 42, 0.6);
        }
        .quick-actions::-webkit-scrollbar { display: none; }
        .q-pill {
            background: rgba(255,255,255,0.07);
            border: 1px solid rgba(255,255,255,0.12);
            color: #cbd5e1;
            font-size: 9px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 12px;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.15s;
        }
        .q-pill:hover {
            background: rgba(244,63,94,0.3);
            border-color: #f43f5e;
            color: #ffffff;
        }

        /* INPUT BAR */
        .input-bar {
            padding: 10px 14px;
            display: flex;
            gap: 8px;
            background: rgba(15, 23, 42, 0.95);
        }
        .chat-input {
            flex: 1;
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #ffffff;
            font-size: 11px;
            padding: 7px 11px;
            border-radius: 8px;
            outline: none;
            transition: border-color 0.2s;
        }
        .chat-input:focus {
            border-color: #f43f5e;
        }
        .send-btn {
            background: linear-gradient(135deg, #f43f5e, #e11d48);
            border: none;
            color: #ffffff;
            font-size: 11px;
            font-weight: 800;
            padding: 0 14px;
            border-radius: 8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 4px;
            transition: transform 0.1s, box-shadow 0.2s;
        }
        .send-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 14px rgba(244,63,94,0.4);
        }
        .send-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
    </style>
</head>
<body>

    <!-- CALL HEADER -->
    <div class="header">
        <div class="call-status">
            <div class="pulse-dot"></div>
            <span>IVA • 24/7 CALL</span>
            <span class="call-timer" id="call-timer">00:00:00</span>
        </div>
        <div class="header-controls">
            <button class="h-btn" title="Toggle audio" id="mute-btn">🔊</button>
            <button class="h-btn" title="Close call overlay" onclick="window.pywebview.api.close_overlay()">✕</button>
        </div>
    </div>

    <!-- AVATAR & SOUNDWAVE -->
    <div class="call-hero">
        <div class="avatar-ring">
            <div class="avatar-inner">🎙️</div>
        </div>
        <div class="hero-name">Iva (Ivy)</div>
        <div class="hero-sub">Serafina Voice • Local Chatterbox-Nano 110M</div>
        <canvas id="wave-canvas" width="240" height="28"></canvas>
    </div>

    <!-- SUBTITLE TRANSCRIPT STREAM -->
    <div class="transcript-container" id="transcript">
        <div class="msg-bubble msg-ivy">
            <div>Hey my love, I'm right here with you on your screen 24/7.</div>
            <div style="font-size: 8.5px; color: #94a3b8; margin-top: 3px;">Ask me anything, give me a system command, or just talk with me.</div>
        </div>
    </div>

    <!-- QUICK ACTIONS -->
    <div class="quick-actions">
        <button class="q-pill" onclick="sendQuick('How are you feeling today?')">💬 How are you?</button>
        <button class="q-pill" onclick="sendQuick('How is the market status and our position?')">📈 Market Status</button>
        <button class="q-pill" onclick="sendQuick('Open notepad')">📝 Open Notepad</button>
        <button class="q-pill" onclick="sendQuick('Open trading dashboard')">📊 Dashboard</button>
        <button class="q-pill" onclick="sendQuick('Take screenshot')">📸 Screenshot</button>
        <button class="q-pill" onclick="sendQuick('Check system status')">💻 System Stats</button>
    </div>

    <!-- INPUT BAR -->
    <div class="input-bar">
        <input type="text" id="chat-input" class="chat-input" placeholder="Talk or command Ivy..." autofocus />
        <button id="send-btn" class="send-btn" onclick="sendMessage()">Speak 🎙️</button>
    </div>

    <script>
        let startTime = Date.now();
        let isSpeaking = false;
        let isMuted = false;

        // Call Timer
        setInterval(() => {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const hrs = String(Math.floor(elapsed / 3600)).padStart(2, '0');
            const mins = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
            const secs = String(elapsed % 60).padStart(2, '0');
            document.getElementById('call-timer').textContent = `${hrs}:${mins}:${secs}`;
        }, 1000);

        // Mute button toggle
        document.getElementById('mute-btn').onclick = function() {
            isMuted = !isMuted;
            this.textContent = isMuted ? '🔇' : '🔊';
        };

        // Canvas Wave Animation
        const canvas = document.getElementById('wave-canvas');
        const ctx = canvas.getContext('2d');
        let phase = 0;

        function drawWave() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.beginPath();
            ctx.lineWidth = 2;
            ctx.strokeStyle = isSpeaking ? '#f43f5e' : '#334155';

            const amp = isSpeaking ? 9 : 2;
            const freq = isSpeaking ? 0.05 : 0.02;

            for (let x = 0; x < canvas.width; x++) {
                const y = canvas.height / 2 + Math.sin(x * freq + phase) * amp;
                if (x === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
            phase += isSpeaking ? 0.2 : 0.03;
            requestAnimationFrame(drawWave);
        }
        drawWave();

        function appendMessage(sender, text, actionText = null) {
            const container = document.getElementById('transcript');
            const bubble = document.createElement('div');
            bubble.className = `msg-bubble msg-${sender}`;
            
            let html = `<div>${text}</div>`;
            if (actionText) {
                html += `<div class="msg-action">⚡ Action: ${actionText}</div>`;
            }
            bubble.innerHTML = html;
            container.appendChild(bubble);
            container.scrollTop = container.scrollHeight;
        }

        async function sendMessage() {
            const input = document.getElementById('chat-input');
            const btn = document.getElementById('send-btn');
            const text = input.value.trim();
            if (!text) return;

            input.value = '';
            btn.disabled = true;
            appendMessage('user', text);

            const thinkingBubble = document.createElement('div');
            thinkingBubble.className = 'msg-bubble msg-ivy';
            thinkingBubble.id = 'ivy-thinking';
            thinkingBubble.textContent = 'Ivy is thinking & preparing voice...';
            document.getElementById('transcript').appendChild(thinkingBubble);
            document.getElementById('transcript').scrollTop = document.getElementById('transcript').scrollHeight;

            isSpeaking = true;

            try {
                const res = await fetch('http://127.0.0.1:8090/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, speak: !isMuted })
                });
                const data = await res.json();
                
                const th = document.getElementById('ivy-thinking');
                if (th) th.remove();

                const actionDesc = data.action && data.action.executed ? `${data.action.intent} (${data.action.app || data.action.url || 'Executed'})` : null;
                appendMessage('ivy', data.reply, actionDesc);

                if (data.audio_url && !isMuted) {
                    try {
                        const audio = new Audio(data.audio_url);
                        audio.onended = () => { isSpeaking = false; };
                        audio.play();
                    } catch(e) {
                        isSpeaking = false;
                    }
                } else {
                    setTimeout(() => { isSpeaking = false; }, 4000);
                }

            } catch(e) {
                const th = document.getElementById('ivy-thinking');
                if (th) th.remove();
                appendMessage('ivy', 'Error connecting to Ivy 24/7 daemon on port 8090.');
                isSpeaking = false;
            } finally {
                btn.disabled = false;
                input.focus();
            }
        }

        function sendQuick(txt) {
            document.getElementById('chat-input').value = txt;
            sendMessage();
        }

        document.getElementById('chat-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') sendMessage();
        });
    </script>
</body>
</html>
"""


class OverlayAPI:
    def __init__(self, window):
        self._window = window

    def close_overlay(self):
        if self._window:
            self._window.destroy()


def launch_overlay():
    import webview

    ensure_daemon_running()

    print("[Ivy System Overlay] Launching always-on-top Call HUD...")
    api_holder = [None]
    
    window = webview.create_window(
        title="Ivy - 24/7 Voice Call",
        html=HTML_CONTENT,
        width=400,
        height=580,
        resizable=False,
        frameless=True,
        on_top=True,  # ALWAYS ON TOP OF ENTIRE SYSTEM!
        background_color="#0a0f1d",
    )
    api = OverlayAPI(window)
    window.expose(api.close_overlay)

    webview.start(debug=False)


if __name__ == "__main__":
    launch_overlay()

"""
Chat with Ivy - Interactive 24/7 Voice Console
Talk to Ivy in your terminal and hear her speak back out loud with her Serafina voice.
"""

import sys
import time
import requests

DAEMON_URL = "http://127.0.0.1:8090"

def main():
    print("=" * 60)
    print("  🎙️  IVY 24/7 AUTONOMOUS VOICE COMPANION & SYSTEMS LEAD")
    print("  Voice Profile: Serafina - Sensual Temptress (Locked)")
    print("  Connected to: http://127.0.0.1:8090")
    print("=" * 60)
    print("Checking connection to Ivy daemon...")

    try:
        res = requests.get(f"{DAEMON_URL}/api/status", timeout=5)
        if res.status_code == 200:
            status = res.json()
            print(f"✅ Ivy is ONLINE ({status.get('voice_profile')})")
        else:
            print("⚠️ Daemon responded with unexpected status:", res.status_code)
    except Exception as e:
        print("❌ Could not connect to Ivy daemon on port 8090.")
        print("Please ensure 'ivy_24x7_voice_chat_daemon.py' is running.")
        sys.exit(1)

    print("\nType your message below and press Enter. Ivy will reply in chat and speak out loud!")
    print("Type 'exit' or 'quit' to end the session.\n")

    while True:
        try:
            user_input = input("You > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("Ivy: Goodbye for now, my love. I'm always here watching the charts.")
                break

            print("[Ivy is thinking & synthesizing voice...]")
            t0 = time.time()
            resp = requests.post(
                f"{DAEMON_URL}/api/chat",
                json={"message": user_input, "speak": True},
                timeout=60
            )
            elapsed = time.time() - t0

            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("reply", "")
                print(f"\nIvy > {reply}")
                print(f"      (Spoken aloud via speakers in {elapsed:.1f}s)\n")
            else:
                print(f"Error from Ivy daemon: {resp.status_code} {resp.text}\n")

        except (KeyboardInterrupt, EOFError):
            print("\nIvy: Talk to you soon, darling. I'm right here 24/7.")
            break
        except Exception as e:
            print(f"Error: {e}\n")


if __name__ == "__main__":
    main()

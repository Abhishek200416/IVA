"""
Iva / Ivy Voice Engine - Agent Integration Module
Authoritative female speech generation engine powered by Chatterbox-Nano (110M).
Pre-conditioned with the user's chosen female voice profile (Serafina).
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, Union

import torch
import soundfile as sf
import numpy as np

PRIMARY_USER_VOICE = Path(os.environ.get("IVA_VOICE_FILE", "assets/voice/iva_default.wav"))
LOCAL_WORKSPACE_VOICE = Path(__file__).parent / "scratch" / "serafina_female_voice.wav"


class IvaVoiceEngine:
    _instance = None

    def __init__(self, device: str = "cpu", ref_clip: Optional[Union[str, Path]] = None):
        from chatterbox.tts_nano import ChatterboxNanoTTS
        print(f"[IvaVoiceEngine] Initializing persistent Chatterbox-Nano model on {device}...")
        self.device = device
        self.model = ChatterboxNanoTTS.from_pretrained(device=device)

        # Resolve authoritative voice clip
        if ref_clip and os.path.exists(str(ref_clip)):
            active_clip = str(ref_clip)
        elif PRIMARY_USER_VOICE.exists():
            active_clip = str(PRIMARY_USER_VOICE)
        elif LOCAL_WORKSPACE_VOICE.exists():
            active_clip = str(LOCAL_WORKSPACE_VOICE)
        else:
            active_clip = None

        self.voice_clip_path = active_clip

        if self.voice_clip_path:
            print(f"[IvaVoiceEngine] Pre-baking Ivy's vocal conditioning from:\n  -> {self.voice_clip_path}")
            # Pre-compute speaker embeddings and conditionals once so generation is ultra-fast
            self.model.prepare_conditionals(self.voice_clip_path)
            print("[IvaVoiceEngine] Voice conditioning locked in memory. Instant generation active.")
        else:
            print("[IvaVoiceEngine] Notice: Using default conds.pt voice.")

        print(f"[IvaVoiceEngine] Ready. Sample rate: {self.model.sr} Hz.")

    @classmethod
    def get_instance(cls, device: str = "cpu", ref_clip: Optional[Union[str, Path]] = None) -> 'IvaVoiceEngine':
        if cls._instance is None:
            cls._instance = cls(device=device, ref_clip=ref_clip)
        return cls._instance

    def speak(
        self,
        text: str,
        output_path: Optional[Union[str, Path]] = None,
        temperature: float = 0.8,
        repetition_penalty: float = 1.2,
        play: bool = False,
    ) -> str:
        """
        Synthesizes text into a WAV file using Ivy's pre-conditioned female voice.
        Returns the absolute path to the generated WAV file.
        If play=True, plays audio immediately through system speakers on Windows.
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty.")

        t0 = time.time()
        # audio_prompt_path=None leverages the pre-conditioned self.model.conds!
        wav = self.model.generate(
            text=text.strip(),
            audio_prompt_path=None,
            cfg_weight=0.0,
            temperature=temperature,
            repetition_penalty=repetition_penalty,
        )
        elapsed = time.time() - t0

        if torch.is_tensor(wav):
            audio_data = wav.squeeze(0).cpu().numpy()
        else:
            audio_data = wav

        # Studio loudness mastering: normalize to peak, apply soft saturation curve (tanh) for rich volume
        max_amp = float(np.max(np.abs(audio_data)))
        if max_amp > 1e-4:
            norm_audio = audio_data / max_amp
            # Soft saturation: 2.6x gain through tanh boosts quiet speech consonants without clipping
            audio_data = np.tanh(norm_audio * 2.6) * 0.99

        duration = len(audio_data) / self.model.sr

        if output_path is None:
            out_dir = Path("scratch/agent_speech")
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / f"ivy_{int(time.time()*1000)}.wav"
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        sf.write(str(output_path), audio_data, self.model.sr)
        print(f"[IvaVoiceEngine] Spoke {duration:.2f}s audio in {elapsed:.2f}s (Boosted to 0.95 peak) -> {output_path}")

        if play and sys.platform == "win32":
            try:
                import winsound
                # SND_ASYNC plays without blocking execution
                winsound.PlaySound(str(output_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
                print(f"[IvaVoiceEngine] Playing through speakers...")
            except Exception as e:
                print(f"[IvaVoiceEngine] Playback notice: {e}")

        return str(output_path.resolve())


def iva_speak(text: str, output_path: Optional[str] = None, play: bool = True) -> str:
    """Convenience function for agent speech with default play=True."""
    engine = IvaVoiceEngine.get_instance()
    return engine.speak(text, output_path=output_path, play=play)


if __name__ == "__main__":
    print("Testing IvaVoiceEngine with Serafina voice conditioning...")
    engine = IvaVoiceEngine.get_instance()
    out = engine.speak("Hi, I am right here with you. My voice is ready.", play=True)
    print(f"Generated output: {out}")

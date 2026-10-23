"""
Iva Voice Assistant - Local Chatterbox-Nano TTS Interface
Provides persistent CPU inference, zero-shot voice cloning, and audio playback/download.
"""

import os
import sys
import time
import math
import random
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import torch
import numpy as np
import soundfile as sf
import librosa
import gradio as gr

from chatterbox.tts_nano import ChatterboxNanoTTS

DEFAULT_SAMPLE_FEMALE = Path("scratch/sample_female_voice.wav")
DEVICE = "cpu"

# Global persistent model singleton
_MODEL_INSTANCE: Optional[ChatterboxNanoTTS] = None

PARALINGUISTIC_TAGS = [
    "[chuckle]", "[laugh]", "[sigh]", "[cough]", "[clear throat]", "[groan]", "[sniff]", "[gasp]"
]

CUSTOM_CSS = """
.container { max-width: 960px; margin: auto; }
.tag-container {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 6px !important;
    margin: 8px 0 !important;
}
.tag-btn {
    min-width: fit-content !important;
    width: auto !important;
    height: 30px !important;
    font-size: 12px !important;
    background: #f0fdf4 !important;
    border: 1px solid #bbf7d0 !important;
    color: #166534 !important;
    border-radius: 6px !important;
    padding: 0 10px !important;
    cursor: pointer !important;
}
.tag-btn:hover {
    background: #dcfce7 !important;
}
.banner-info {
    background: #f8fafc;
    border-left: 4px solid #3b82f6;
    padding: 12px;
    border-radius: 4px;
    margin-bottom: 12px;
    font-size: 13px;
    line-height: 1.5;
}
"""

INSERT_TAG_JS = """
(tag_val, current_text) => {
    const textarea = document.querySelector('#tts_text_input textarea');
    if (!textarea) return current_text + " " + tag_val;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    let prefix = " ";
    let suffix = " ";
    if (start === 0 || current_text[start - 1] === ' ') prefix = "";
    if (end < current_text.length && current_text[end] === ' ') suffix = "";
    return current_text.slice(0, start) + prefix + tag_val + suffix + current_text.slice(end);
}
"""


def get_model() -> ChatterboxNanoTTS:
    """Persistent singleton model loader."""
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is None:
        print(f"[Iva Voice] Initializing ChatterboxNanoTTS on {DEVICE}...")
        _MODEL_INSTANCE = ChatterboxNanoTTS.from_pretrained(device=DEVICE)
        print("[Iva Voice] Model loaded into persistent memory.")
    return _MODEL_INSTANCE


def set_seed(seed: int):
    if seed > 0:
        torch.manual_seed(seed)
        np.random.seed(seed)
        random.seed(seed)


def validate_reference_audio(audio_path: Optional[str]) -> Tuple[bool, str, float]:
    """Validates the reference audio recording per Chatterbox-Nano requirements."""
    if not audio_path:
        return True, "Default voice (official conds.pt profile)", 0.0
    
    path = Path(audio_path)
    if not path.exists():
        return False, f"File does not exist: {audio_path}", 0.0
    
    try:
        info = sf.info(str(path))
        duration = info.duration
        if duration <= 5.0:
            return False, f"Audio prompt must be longer than 5.0s (uploaded clip is only {duration:.2f}s).", duration
        return True, f"Valid reference recording ({duration:.1f}s, {info.samplerate}Hz)", duration
    except Exception as e:
        return False, f"Could not read audio file: {e}", 0.0


def synthesize_speech(
    text: str,
    ref_audio_path: Optional[str],
    temperature: float,
    repetition_penalty: float,
    top_p: float,
    top_k: int,
    seed: int,
    norm_loudness: bool,
    progress=gr.Progress(),
):
    if not text or not text.strip():
        raise gr.Error("Please enter text for the assistant to speak.")

    clean_text = text.strip()
    progress(0.1, desc="Validating inputs & reference audio...")

    # Validate reference audio if provided
    is_valid, validation_msg, ref_duration = validate_reference_audio(ref_audio_path)
    if not is_valid:
        raise gr.Error(f"Reference Audio Error: {validation_msg}")

    # Set seed if non-zero
    if seed != 0:
        set_seed(int(seed))

    progress(0.25, desc="Loading persistent Chatterbox-Nano model...")
    model = get_model()

    progress(0.4, desc="Synthesizing tokens with T3 transformer...")
    t_start = time.time()

    prompt_path = ref_audio_path if ref_audio_path and os.path.exists(ref_audio_path) else None

    try:
        wav = model.generate(
            clean_text,
            audio_prompt_path=prompt_path,
            temperature=float(temperature),
            repetition_penalty=float(repetition_penalty),
            top_p=float(top_p),
            top_k=int(top_k),
            norm_loudness=bool(norm_loudness),
        )
    except Exception as e:
        raise gr.Error(f"Synthesis failed: {e}")

    progress(0.9, desc="Encoding audio output to WAV...")
    t_end = time.time()
    elapsed = t_end - t_start

    # Convert tensor to numpy
    if torch.is_tensor(wav):
        audio_data = wav.squeeze(0).cpu().numpy()
    else:
        audio_data = wav

    duration = len(audio_data) / model.sr
    rtf = elapsed / duration if duration > 0 else 0.0

    # Save to a temporary WAV file for playback and download
    temp_dir = Path("scratch/generated_audio")
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_file = temp_dir / f"iva_speech_{int(time.time())}.wav"
    sf.write(str(out_file), audio_data, model.sr)

    voice_mode = f"Cloned Speaker ({Path(ref_audio_path).name}, {ref_duration:.1f}s)" if prompt_path else "Default Voice (conds.pt female profile)"

    metrics_text = (
        f"**Voice Mode**: {voice_mode}\n\n"
        f"**Generation Time**: {elapsed:.2f} s | "
        f"**Audio Duration**: {duration:.2f} s | "
        f"**Real-Time Factor (RTF)**: {rtf:.2f}x\n\n"
        f"**Audio Specs**: {model.sr} Hz, 16-bit PCM WAV ({len(audio_data):,} samples)"
    )

    progress(1.0, desc="Completed!")
    return str(out_file), metrics_text


def load_demo_female_clip():
    """Helper to populate the reference audio box with the verified female clip."""
    if DEFAULT_SAMPLE_FEMALE.exists():
        return str(DEFAULT_SAMPLE_FEMALE.resolve())
    return None


def clear_reference_clip():
    """Helper to revert to default built-in voice."""
    return None


def create_ui():
    with gr.Blocks(title="Iva Voice Assistant - Chatterbox-Nano", css=CUSTOM_CSS) as demo:
        gr.Markdown(
            "# 🎙️ Iva Voice Assistant\n"
            "### Local High-Fidelity Female Text-to-Speech Engine Powered by Chatterbox-Nano (110M)"
        )

        with gr.Row():
            with gr.Column(scale=3):
                gr.HTML(
                    """
                    <div class="banner-info">
                        <strong>Model Specs:</strong> Resemble AI Chatterbox-Nano (110M parameters) running on local Intel CPU.<br>
                        <strong>Voice Characteristics:</strong> Without a reference recording, the engine utilizes the official default conditioning profile (<code>conds.pt</code>), producing a natural adult female tone (Mean pitch ~225 Hz).<br>
                        <strong>Custom Voice Cloning:</strong> Upload an authorized reference recording of <strong>10–15 seconds</strong> (minimum 5.0 seconds strictly enforced by model architecture) to zero-shot clone a specific speaker's tone.
                    </div>
                    """
                )

                text_input = gr.Textbox(
                    value="Hello! I am Iva, your AI systems architect and engineering partner. How can I assist you with your project today? [chuckle]",
                    label="Assistant Speech Text",
                    placeholder="Enter what you want Iva to speak...",
                    lines=4,
                    elem_id="tts_text_input",
                )

                gr.Markdown("###### Insert Paralinguistic Expression Tags:")
                with gr.Row(elem_classes=["tag-container"]):
                    for tag in PARALINGUISTIC_TAGS:
                        tag_btn = gr.Button(tag, elem_classes=["tag-btn"])
                        tag_btn.click(
                            fn=None,
                            inputs=[tag_btn, text_input],
                            outputs=text_input,
                            js=INSERT_TAG_JS,
                        )

                with gr.Group():
                    ref_audio = gr.Audio(
                        sources=["upload", "microphone"],
                        type="filepath",
                        label="Voice Reference Recording (Optional - Required > 5.0s)",
                    )
                    with gr.Row():
                        load_demo_btn = gr.Button("Use Included Female Voice Sample", size="sm")
                        clear_ref_btn = gr.Button("Reset to Default Voice", size="sm")

                generate_btn = gr.Button("Generate Speech ⚡", variant="primary", size="lg")

            with gr.Column(scale=2):
                gr.Markdown("### Generated Audio Output")
                audio_output = gr.Audio(
                    label="Audio Playback & Download",
                    type="filepath",
                    interactive=False,
                )

                metrics_output = gr.Markdown(
                    "Click **Generate Speech** to synthesize audio and view CPU inference metrics."
                )

                with gr.Accordion("Advanced Generation Parameters", open=False):
                    temperature = gr.Slider(0.1, 1.5, value=0.8, step=0.05, label="Temperature (Speech variability)")
                    repetition_penalty = gr.Slider(1.0, 2.0, value=1.2, step=0.05, label="Repetition Penalty")
                    top_p = gr.Slider(0.5, 1.0, value=0.95, step=0.01, label="Top P")
                    top_k = gr.Slider(50, 1000, value=1000, step=50, label="Top K")
                    seed = gr.Number(value=0, label="Random Seed (0 = stochastic)", precision=0)
                    norm_loudness = gr.Checkbox(value=True, label="Normalize Loudness (-27 LUFS)")
                    gr.Markdown(
                        "*Note: Per Resemble AI specifications, CFG weight and exaggeration parameters are disabled in Nano to maintain maximum CPU efficiency.*"
                    )

        # Wire callbacks
        generate_btn.click(
            fn=synthesize_speech,
            inputs=[
                text_input,
                ref_audio,
                temperature,
                repetition_penalty,
                top_p,
                top_k,
                seed,
                norm_loudness,
            ],
            outputs=[audio_output, metrics_output],
        )

        load_demo_btn.click(
            fn=load_demo_female_clip,
            inputs=[],
            outputs=[ref_audio],
        )

        clear_ref_btn.click(
            fn=clear_reference_clip,
            inputs=[],
            outputs=[ref_audio],
        )

    return demo


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7865))
    print(f"Pre-warming Chatterbox-Nano model...")
    get_model()
    app = create_ui()
    print(f"Launching Iva Voice UI on http://127.0.0.1:{port}...")
    app.launch(server_name="127.0.0.1", server_port=port, inbrowser=False)

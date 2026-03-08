import subprocess
import os


def normalize_audio(input_path: str) -> str:
    """
    Convert any audio format into clean
    mono 16kHz wav.
    """

    output_path = input_path + "_normalized.wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        output_path
    ]

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return output_path


def trim_silence(input_path: str) -> str:
    """
    Remove long silence segments from audio.
    """

    output_path = input_path.replace(".wav", "_trimmed.wav")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-af",
        "silenceremove=start_periods=1:start_duration=1:start_threshold=-40dB:"
        "stop_periods=-1:stop_duration=1:stop_threshold=-40dB",
        output_path
    ]

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return output_path
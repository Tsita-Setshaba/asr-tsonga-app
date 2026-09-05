import torch
import torchaudio
import os
import random
import io
from pathlib import Path
from typing import Union
from transformers import AutoProcessor, AutoModelForCTC
import numpy as np
import requests

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Hugging Face repo id where the model files were uploaded
MODEL_REPO_ID = "Tsita-Mogau/ASR-Tsonga"

# CloudConvert key now comes from the environment (set via .env locally,
# or Space "Variables and secrets" once deployed) - never hardcode this.
CLOUDCONVERT_API_KEY = os.getenv("CLOUDCONVERT_API_KEY")


class ASR:
    def __init__(self, repo_id: str = MODEL_REPO_ID, audio_folder: str = None):
        # Load processor + model directly from the Hugging Face Hub
        self.processor = AutoProcessor.from_pretrained(repo_id)
        self.model = AutoModelForCTC.from_pretrained(repo_id).to(device)
        self.model.eval()
        self.audio_folder = audio_folder
        self.cc_api_key = CLOUDCONVERT_API_KEY

    def _convert_to_wav_via_api(self, input_path: str, output_path: str):
        """Convert audio to WAV using CloudConvert API"""
        if not self.cc_api_key:
            raise RuntimeError(
                "CLOUDCONVERT_API_KEY is not set. Add it to your .env "
                "or Space secrets before converting non-WAV audio."
            )

        base_url = "https://api.cloudconvert.com/v2"
        headers = {"Authorization": f"Bearer {self.cc_api_key}"}
        filename = Path(input_path).name

        create_task = {
            "tasks": {
                "import-file": {"operation": "import/upload"},
                "convert-file": {
                    "operation": "convert",
                    "input": "import-file",
                    "output_format": "wav",
                },
                "export-file": {
                    "operation": "export/url",
                    "input": "convert-file"
                }
            }
        }

        resp = requests.post(f"{base_url}/jobs", json=create_task, headers=headers)
        if resp.status_code != 201:
            raise RuntimeError(f"CloudConvert job create failed: {resp.text}")
        job = resp.json()["data"]

        upload_task = [t for t in job["tasks"] if t["name"] == "import-file"][0]
        upload_url = upload_task["result"]["form"]["url"]
        form_data = upload_task["result"]["form"]["parameters"]

        with open(input_path, "rb") as f:
            files = {"file": (filename, f)}
            upload_resp = requests.post(upload_url, data=form_data, files=files)
            if upload_resp.status_code not in (200, 201, 204):
                raise RuntimeError(f"CloudConvert upload failed: {upload_resp.text}")

        while True:
            job_status = requests.get(f"{base_url}/jobs/{job['id']}", headers=headers).json()
            status = job_status["data"]["status"]
            if status in ["finished", "error"]:
                break

        if status == "error":
            raise RuntimeError(f"CloudConvert conversion failed: {job_status}")

        export_task = [t for t in job_status["data"]["tasks"] if t["name"] == "export-file"][0]
        file_url = export_task["result"]["files"][0]["url"]

        wav_data = requests.get(file_url)
        with open(output_path, "wb") as f:
            f.write(wav_data.content)

    def _load_and_preprocess_audio(self, audio_input: Union[str, bytes, torch.Tensor, np.ndarray]) -> torch.Tensor:
        """Load and preprocess audio from various input types"""
        if isinstance(audio_input, str):
            if not os.path.exists(audio_input):
                raise FileNotFoundError(f"Audio file not found: {audio_input}")

            ext = Path(audio_input).suffix.lower()

            if ext == ".wav":
                waveform, sample_rate = torchaudio.load(audio_input)
            else:
                temp_wav = "temp_audio.wav"
                self._convert_to_wav_via_api(audio_input, temp_wav)
                waveform, sample_rate = torchaudio.load(temp_wav)
                os.remove(temp_wav)

        elif isinstance(audio_input, (bytes, bytearray)):
            audio_buffer = io.BytesIO(audio_input)
            waveform, sample_rate = torchaudio.load(audio_buffer)

        elif isinstance(audio_input, (torch.Tensor, np.ndarray)):
            if isinstance(audio_input, np.ndarray):
                waveform = torch.from_numpy(audio_input).float()
            else:
                waveform = audio_input.float()
            sample_rate = 16000
        else:
            raise ValueError(f"Unsupported audio input type: {type(audio_input)}")

        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
            waveform = resampler(waveform)

        if waveform.dim() > 1 and waveform.size(0) > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)

        return waveform.squeeze()

    def transcribe(self, audio_input: Union[str, bytes, torch.Tensor, np.ndarray]) -> str:
        """Transcribe audio from a file path, bytes, tensor, or numpy array"""
        try:
            waveform = self._load_and_preprocess_audio(audio_input)

            inputs = self.processor(
                waveform,
                sampling_rate=16000,
                return_tensors="pt",
                padding=True
            )

            input_values = inputs.input_values.to(device)

            with torch.no_grad():
                logits = self.model(input_values).logits

            predicted_ids = torch.argmax(logits, dim=-1)
            transcription = self.processor.batch_decode(predicted_ids)[0]

            return transcription

        except Exception as e:
            raise RuntimeError(f"Transcription failed: {e}")

    def get_sample_files(self, num_samples=5) -> list:
        """Get random sample audio files from the audio folder"""
        if not self.audio_folder:
            raise ValueError("Audio folder not specified in initialization")

        audio_extensions = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac', '.webm'}
        all_files = []

        for root, _, files in os.walk(self.audio_folder):
            for file in files:
                if Path(file).suffix.lower() in audio_extensions:
                    all_files.append(os.path.join(root, file))

        if not all_files:
            raise FileNotFoundError(f"No audio files found in {self.audio_folder}")

        return random.sample(all_files, min(num_samples, len(all_files)))

    def transcribe_samples(self, num_samples=5):
        """Transcribe random sample files from the audio folder"""
        sample_files = self.get_sample_files(num_samples)
        print("Selected files:\n" + "\n".join(sample_files))

        for file_path in sample_files:
            try:
                text = self.transcribe(file_path)
                print(f"\nFile: {file_path}")
                print(f"Transcription: {text}")
            except Exception as e:
                print(f"\nFile: {file_path}")
                print(f"Error: {e}")


# Example usage:
# asr_instance = ASR()  # loads from Tsita-Mogau/ASR-Tsonga on the Hub
# transcription = asr_instance.transcribe("audio.wav")

"""Образцы голосов Silero на фразах Stevens. Запуск — tools/voice-samples.sh (в Docker, ничего не ставит в систему)."""
import os
import wave

import torch

PHRASES = {
    "1-zapisal": "Добрый вечер. Записал встречу с Иваном на завтра, в пятнадцать ноль-ноль.",
    "2-uslugi": "К вашим услугам. Что-нибудь ещё?",
    "3-plany": "На сегодня у вас три дела. Первое — созвон с командой в десять утра.",
    "4-konflikt": "В это время у вас уже назначена встреча с Марией. Оставить обе или выбрать другое время?",
}
SPEAKERS = ["aidar", "eugene", "baya", "kseniya", "xenia"]
OUT = "/out"
RATE = 48000

torch.set_num_threads(4)
model_path = "/tmp/v4_ru.pt"
if not os.path.exists(model_path):
    torch.hub.download_url_to_file("https://models.silero.ai/models/tts/ru/v4_ru.pt", model_path)
model = torch.package.PackageImporter(model_path).load_pickle("tts_models", "model")
model.to(torch.device("cpu"))

for speaker in SPEAKERS:
    for name, text in PHRASES.items():
        audio = model.apply_tts(text=text, speaker=speaker, sample_rate=RATE, put_accent=True, put_yo=True)
        pcm = (audio.clamp(-1, 1) * 32767).to(torch.int16).numpy().tobytes()
        path = f"{OUT}/silero-{speaker}-{name}.wav"
        with wave.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes(pcm)
        print("готово:", path.replace(OUT, "voice-samples"))

/**
 * Д12 Озвучка: фронт читает speech (или text, если speech: null)
 * браузерным синтезом речи. Бэк для этого не нужен.
 */
export const canSpeak = (): boolean =>
  typeof window !== "undefined" && "speechSynthesis" in window;

function russianVoice(): SpeechSynthesisVoice | undefined {
  return window.speechSynthesis
    .getVoices()
    .find((voice) => voice.lang.toLowerCase().startsWith("ru"));
}

/** Озвучивает фразу. onEnd вызывается и после конца речи, и при ошибке */
export function speak(text: string, onEnd?: () => void): void {
  if (!canSpeak() || !text.trim()) {
    onEnd?.();
    return;
  }
  window.speechSynthesis.cancel();
  // Имя латиницей синтез читает плохо: в text — Stevens, вслух — Стивенс (Р-120).
  const utterance = new SpeechSynthesisUtterance(
    text.replace(/Stevens/g, "Стивенс"),
  );
  utterance.lang = "ru-RU";
  const voice = russianVoice();
  if (voice) utterance.voice = voice;
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    onEnd?.();
  };
  utterance.onend = finish;
  utterance.onerror = finish;
  window.speechSynthesis.speak(utterance);
}

export function stopSpeaking(): void {
  if (canSpeak()) window.speechSynthesis.cancel();
}

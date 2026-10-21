/** Д12: озвучка ответов на голосовые сообщения — 07-extras.md, раздел 7. */
import { emitSpeech, isSpeaking, onAssistantResponse, onUiActivity } from '../../state/events';

let voice: SpeechSynthesisVoice | null = null;

function pickVoice(): void {
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith('ru'));
  voice = voices.find((v) => v.localService) ?? voices[0] ?? null;
}

function stop(): void {
  if (!isSpeaking()) return;
  window.speechSynthesis.cancel();
  emitSpeech('cancelled');
}

export function init(): void {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
  pickVoice();
  window.speechSynthesis.addEventListener('voiceschanged', pickVoice);

  onAssistantResponse((response, request) => {
    if (request.source !== 'voice' || !voice) return;
    const text = response.speech ?? response.text;
    if (!text) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = voice;
    utterance.lang = voice.lang;
    utterance.onend = () => isSpeaking() && emitSpeech('end');
    utterance.onerror = () => isSpeaking() && emitSpeech('end');
    emitSpeech('start');
    window.speechSynthesis.speak(utterance);
  });

  // Обрывает любое действие: кнопка, ввод, микрофон, «Новый диалог», сворачивание вкладки
  onUiActivity((kind) => {
    if (['typing', 'button-press', 'recording-start', 'new-dialog', 'tab-hidden'].includes(kind)) stop();
  });
}

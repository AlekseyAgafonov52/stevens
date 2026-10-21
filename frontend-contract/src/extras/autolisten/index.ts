/** Д13: автослушание после уточнения — 07-extras.md, раздел 8. */
import { isSpeaking, onAssistantResponse, onSpeech, onUiActivity } from '../../state/events';
import { startRecording } from '../../state/recording';
import { voice } from '../../voice';

const DELAY_MS = 600;

let timer: ReturnType<typeof setTimeout> | undefined;
let waitingForSpeech = false;

function cancel(): void {
  clearTimeout(timer);
  waitingForSpeech = false;
}

function listen(): void {
  waitingForSpeech = false;
  if (document.visibilityState !== 'visible') return;
  startRecording({ auto: true });
}

export function init(): void {
  onAssistantResponse((response, request) => {
    cancel();
    if (request.source !== 'voice' || !response.awaiting_reply) return;
    if (document.visibilityState !== 'visible' || !voice.hasPermission()) return;
    // Озвучка (Д12) могла начаться в этом же ответе — проверяем после неё
    setTimeout(() => {
      if (isSpeaking()) waitingForSpeech = true;
      else timer = setTimeout(listen, DELAY_MS);
    }, 0);
  });

  onSpeech((phase) => {
    if (phase === 'end' && waitingForSpeech) listen();
    if (phase === 'cancelled') cancel();
  });

  // Любое действие человека до старта отменяет автослушание
  onUiActivity((kind) => {
    if (['typing', 'button-press', 'recording-start', 'new-dialog', 'tab-hidden', 'request-start'].includes(kind)) cancel();
  });
}

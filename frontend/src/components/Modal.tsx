/** Окно подтверждения */
import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Pill } from './Pill';

type Props = {
  title: string;
  text: string;
  confirm: string;
  cancel: string;
  onConfirm: () => void;
  onCancel: () => void;
};

export function Modal({ title, text, confirm, cancel, onConfirm, onCancel }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const stayRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef(onCancel);
  useEffect(() => {
    cancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    stayRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cancelRef.current();
      if (e.key === 'Tab' && boxRef.current) {
        const items = boxRef.current.querySelectorAll<HTMLElement>('button');
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous?.focus?.();
    };
  }, []);

  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" ref={boxRef}>
        <div className="modal__title" id="modal-title">{title}</div>
        <div className="modal__text">{text}</div>
        <div className="modal__buttons">
          <Pill variant="secondary" ref={stayRef} onClick={onCancel}>{cancel}</Pill>
          <button type="button" className="pill pill--selected pill--action" onClick={onConfirm}>{confirm}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

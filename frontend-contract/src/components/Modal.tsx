import { useEffect, useRef } from "react";
import { T } from "../content/texts";
import { Pill } from "./Pill";

export function Modal({
  title,
  text,
  confirm,
  onCancel,
  onConfirm,
}: {
  title: string;
  text: string;
  confirm: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby="modal-title"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div className="modal-inner">
        <h2 id="modal-title">{title}</h2>
        <p>{text}</p>
        <div className="pill-row">
          <Pill autoFocus secondary onClick={onCancel}>
            {T.new_dialog_cancel}
          </Pill>
          <Pill selected onClick={onConfirm}>
            {confirm}
          </Pill>
        </div>
      </div>
    </dialog>
  );
}

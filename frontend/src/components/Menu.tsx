/** Выпадающее меню шапки */
import { Check } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';

/** checked задан — переключатель: галочка справа, меню не закрывается, можно нажимать туда-сюда */
export type MenuItem = { label: string; onSelect: () => void; checked?: boolean };

type Props = {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  heading?: string;
  items: MenuItem[];
};

export function Menu({ trigger, heading, items }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (!open) return;
    itemRefs.current[0]?.focus();
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const index = itemRefs.current.findIndex((el) => el === document.activeElement);
        const step = e.key === 'ArrowDown' ? 1 : -1;
        const next = (index + step + items.length) % items.length;
        itemRefs.current[next]?.focus();
      }
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, items.length]);

  return (
    <div className="menu" ref={rootRef}>
      {trigger({ open, toggle: () => setOpen((v) => !v) })}
      {open && (
        <div className="menu__list" role="menu">
          {heading && <div className="menu__heading">{heading}</div>}
          {items.map((item, index) => (
            <button
              key={item.label}
              ref={(el) => { itemRefs.current[index] = el; }}
              type="button"
              role={item.checked === undefined ? 'menuitem' : 'menuitemcheckbox'}
              aria-checked={item.checked}
              className="menu__item"
              onClick={() => { if (item.checked === undefined) setOpen(false); item.onSelect(); }}
            >
              {item.label}
              {item.checked && <Check className="menu__check" size={16} strokeWidth={1.5} aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

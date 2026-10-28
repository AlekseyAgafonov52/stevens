import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

export type PillVariant = 'primary' | 'secondary' | 'selected' | 'dimmed';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: PillVariant; icon?: ReactNode };

/** Кнопка-пилюля */
export const Pill = forwardRef<HTMLButtonElement, Props>(function Pill(
  { variant = 'primary', icon, children, className = '', ...rest },
  ref,
) {
  const inert = variant === 'selected' || variant === 'dimmed';
  return (
    <button
      ref={ref}
      type="button"
      className={`pill pill--${variant} ${className}`}
      disabled={inert || rest.disabled}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
});

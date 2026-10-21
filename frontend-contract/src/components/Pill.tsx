import type { ButtonHTMLAttributes, ReactNode } from "react";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  secondary?: boolean;
  selected?: boolean;
}
export function Pill({
  children,
  secondary,
  selected,
  className = "",
  ...props
}: Props) {
  return (
    <button
      type="button"
      className={`pill ${secondary ? "pill-secondary" : ""} ${selected ? "pill-selected" : ""} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

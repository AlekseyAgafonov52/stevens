/** Три точки индикатора — 02-screens.md, 2.3 */
export function Dots({ className = '' }: { className?: string }) {
  return (
    <span className={`dots ${className}`} aria-hidden="true">
      <span className="thinking-dot" />
      <span className="thinking-dot" />
      <span className="thinking-dot" />
    </span>
  );
}

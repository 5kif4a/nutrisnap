interface Props {
  label: string;
  value: number;
  target: number | null;
  color: string;
}

export function MacroBar({ label, value, target, color }: Props) {
  const pct = target && target > 0 ? Math.min((value / target) * 100, 100) : 0;
  return (
    <div className="min-w-0 flex-1">
      <div className="mb-1 text-xs leading-tight">
        <div className="truncate font-medium text-tg-text">{label}</div>
        <div className="truncate text-tg-hint">
          {Math.round(value)}
          {target != null ? ` / ${target}` : ""} г
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-tg-border">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
}

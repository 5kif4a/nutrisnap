interface Props {
  label: string;
  value: number;
  target: number | null;
  color: string;
}

export function MacroBar({ label, value, target, color }: Props) {
  const pct =
    target && target > 0 ? Math.min((value / target) * 100, 100) : 0;
  return (
    <div className="flex-1">
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="font-medium text-tg-text">{label}</span>
        <span className="text-tg-hint">
          {Math.round(value)}
          {target != null ? ` / ${target}` : ""} г
        </span>
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

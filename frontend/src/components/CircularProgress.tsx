interface Props {
  value: number;
  max: number;
  label: string;
  unit?: string;
}

export function CircularProgress({ value, max, label, unit = "" }: Props) {
  const size = 168;
  const stroke = 14;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const pct = max > 0 ? Math.min(value / max, 1) : 0;
  const over = max > 0 && value > max;

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--tg-border)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={over ? "#ef4444" : "var(--tg-button)"}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - pct)}
          style={{ transition: "stroke-dashoffset 0.5s ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold text-tg-text">
          {Math.round(value)}
        </span>
        <span className="text-sm text-tg-hint">
          / {Math.round(max)} {unit}
        </span>
        <span className="mt-1 text-xs uppercase tracking-wide text-tg-hint">
          {label}
        </span>
      </div>
    </div>
  );
}

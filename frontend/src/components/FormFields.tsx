import { ChevronDown } from "lucide-react";
import type {
  FieldError,
  FieldValues,
  Path,
  UseFormRegister,
} from "react-hook-form";

/* ───────── Themed form primitives — shared between Profile, FoodForm,
   Onboarding etc. Generic over the form-values shape so each consumer
   gets full type-safety for its own field names. ───────── */

interface NumberFieldProps<T extends FieldValues> {
  label: string;
  name: Path<T>;
  register: UseFormRegister<T>;
  error?: FieldError;
  step?: number | "any";
  placeholder?: string;
}

export function NumberField<T extends FieldValues>({
  label,
  name,
  register,
  error,
  step = "any",
  placeholder,
}: NumberFieldProps<T>) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-tg-hint">{label}</span>
      <input
        type="number"
        inputMode="numeric"
        step={step}
        placeholder={placeholder}
        {...register(name, {
          // RHF reads <input> value as string by default; coerce to number
          // for the schema. Empty string → null so the resolver can apply
          // its conditional "required" rules per cross-field validation.
          setValueAs: (v) => (v === "" || v == null ? null : Number(v)),
        })}
        className="w-full rounded-xl border border-[var(--glass-stroke)] bg-black/20 px-3.5 py-2.5 text-base text-tg-text outline-none transition focus:border-[var(--accent)]"
      />
      {error && (
        <span className="mt-1 block text-xs text-red-400">{error.message}</span>
      )}
    </label>
  );
}

interface SelectFieldProps<T extends FieldValues> {
  label: string;
  name: Path<T>;
  register: UseFormRegister<T>;
  options: { v: string; label: string }[];
  error?: FieldError;
}

export function SelectField<T extends FieldValues>({
  label,
  name,
  register,
  options,
  error,
}: SelectFieldProps<T>) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-tg-hint">{label}</span>
      <div className="relative">
        <select
          {...register(name)}
          className="w-full appearance-none rounded-xl border border-[var(--glass-stroke)] bg-black/20 px-3.5 py-2.5 pr-10 text-base text-tg-text outline-none transition focus:border-[var(--accent)]"
        >
          {options.map((o) => (
            <option key={o.v} value={o.v}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          size={18}
          aria-hidden="true"
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-tg-hint"
        />
      </div>
      {error && (
        <span className="mt-1 block text-xs text-red-400">{error.message}</span>
      )}
    </label>
  );
}

interface SegmentedProps<T extends string> {
  options: { v: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: SegmentedProps<T>) {
  return (
    <div className="grid grid-flow-col auto-cols-fr gap-1 rounded-xl border border-[var(--glass-stroke)] bg-black/20 p-1">
      {options.map((o) => {
        const selected = value === o.v;
        return (
          <button
            key={o.v}
            type="button"
            onClick={() => onChange(o.v)}
            className="rounded-lg px-2 py-2 text-sm font-medium transition"
            style={{
              color: selected ? "#ffffff" : "var(--tg-hint)",
              background: selected ? "var(--accent)" : "transparent",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Toggle({ on }: { on: boolean }) {
  return (
    <span
      role="presentation"
      className="relative inline-block h-7 w-12 shrink-0 rounded-full transition"
      style={{
        // iOS-style neutral grey for the off state — readable on both light
        // and dark Telegram themes (white-on-light was invisible before).
        background: on ? "var(--accent)" : "rgba(120, 120, 128, 0.32)",
      }}
    >
      <span
        className="absolute top-0.5 h-6 w-6 rounded-full bg-white transition-all"
        style={{
          left: on ? "22px" : "2px",
          boxShadow: "0 2px 4px rgba(0, 0, 0, 0.25)",
        }}
      />
    </span>
  );
}

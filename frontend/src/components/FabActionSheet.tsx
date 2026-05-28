import { Camera, MessageSquare, Pencil } from "lucide-react";
import { useRef, useState } from "react";
import { BottomSheet } from "./BottomSheet";
import { api } from "../lib/api";
import { closeToBot } from "../telegram";
import type { ResolvedItem } from "../types";

/* ───────── Bottom sheet shown when the user taps the «+» FAB.
   Three entry points; only one (Через чат) actually closes the Mini App. */

interface Props {
  open: boolean;
  onClose: () => void;
  /** User picked «Ручное заполнение» — parent opens FoodForm. */
  onPickManual: () => void;
  /** Vision graph resolved items on a photo — parent should show the
   * meal-type picker with these items prefilled. */
  onPhotoResolved: (items: ResolvedItem[]) => void;
  /** Surface errors via the parent's toast layer. */
  onError: (message: string) => void;
}

export function FabActionSheet({
  open,
  onClose,
  onPickManual,
  onPhotoResolved,
  onError,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);

  const handleCameraPick = () => {
    if (uploading) return;
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // reset so the same file can be re-picked
    if (!file) return;
    setUploading(true);
    try {
      const result = await api.entryFromPhoto(file);
      if (!result.items.length) {
        onError(
          result.reason
            ? `⚠️ ${humanizeReason(result.reason)}`
            : "⚠️ Не нашёл еду на фото",
        );
        return;
      }
      onPhotoResolved(result.items);
      onClose();
    } catch (err) {
      onError(`⚠️ ${(err as Error).message}`);
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <BottomSheet open={open} onClose={onClose} title="Добавить приём пищи">
        <div className="space-y-2 pb-2">
          <ActionRow
            icon={<Pencil size={20} />}
            title="Ручное заполнение"
            subtitle="Введи КБЖУ и порцию вручную"
            disabled={uploading}
            onClick={() => {
              onPickManual();
              onClose();
            }}
          />
          <ActionRow
            icon={<Camera size={20} />}
            title="Камера / медиатека"
            subtitle="Сфотографируй блюдо — распознаю еду"
            disabled={uploading}
            loading={uploading}
            onClick={handleCameraPick}
          />
          <ActionRow
            icon={<MessageSquare size={20} />}
            title="Через чат"
            subtitle="Открыть бота — фото / голос / текст"
            disabled={uploading}
            onClick={() => {
              closeToBot();
              onClose();
            }}
          />
        </div>
      </BottomSheet>

      {/* Hidden file input — opens native camera / media picker on mobile.
          `capture` is a hint, not a hard switch: iOS shows a chooser between
          camera and library; Android opens the camera directly. */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={handleFileChange}
        className="hidden"
      />
    </>
  );
}

interface RowProps {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
}

function ActionRow({
  icon,
  title,
  subtitle,
  onClick,
  disabled,
  loading,
}: RowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex w-full items-center gap-3 rounded-2xl bg-tg-card px-4 py-3 text-left transition active:scale-[0.98] disabled:opacity-60"
    >
      <span
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
      >
        {loading ? (
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-tg-hint border-t-transparent" />
        ) : (
          icon
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold text-tg-text">{title}</div>
        <div className="mt-0.5 text-xs text-tg-hint">{subtitle}</div>
      </div>
    </button>
  );
}

function humanizeReason(reason: string): string {
  if (reason.includes("non_food")) return "На фото нет еды";
  if (reason.includes("unsafe")) return "Фото не прошло модерацию";
  if (reason.includes("abuse")) return "Запрос отклонён";
  return reason.length > 80 ? "Не удалось разобрать фото" : reason;
}

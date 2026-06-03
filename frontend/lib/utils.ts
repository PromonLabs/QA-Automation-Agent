import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—"
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}m ${s}s`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  return new Date(iso).toLocaleString()
}

export function statusColor(status: string): string {
  switch (status) {
    case "success": return "text-white bg-white/10 border-white/20"
    case "failed": return "text-white/60 bg-white/5 border-white/10"
    case "running": return "text-white bg-white/15 border-white/25"
    case "pending": return "text-white/50 bg-white/5 border-white/10"
    case "cancelled": return "text-white/40 bg-white/5 border-white/10"
    default: return "text-white/50 bg-white/5 border-white/10"
  }
}

export function logColor(level: string): string {
  switch (level) {
    case "success": return "text-white"
    case "error": return "text-white/50"
    case "warning": return "text-white/70"
    case "info": return "text-white/60"
    default: return "text-white/50"
  }
}

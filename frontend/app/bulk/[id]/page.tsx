"use client"

import { useEffect, useRef, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import { bulkApi, executionApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { BulkRun, BulkItem } from "@/types"
import { formatDuration } from "@/lib/utils"
import {
  CheckCircle2, XCircle, Loader2, Clock,
  ArrowLeft, X, ChevronRight, ImageIcon,
  ZoomIn,
} from "lucide-react"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const SHOT_LABELS = ["Before Data", "Payment", "After Data"]

// step_015_error_step_015_1781510269.png  → true
const isErrorShot = (filename: string) => /^step_\d+_error_/i.test(filename)

// Extract step number from error screenshot name: step_015_error_... → "Step 15"
function errorStepLabel(filename: string): string {
  const m = filename.match(/^step_(\d+)_error_/i)
  return m ? `Error at Step ${parseInt(m[1], 10)}` : "Error"
}

function ScreenshotThumb({
  url,
  label,
  isError = false,
  onClick,
}: {
  url: string
  label: string
  isError?: boolean
  onClick: () => void
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-center gap-1.5">
        <span className={`text-xs text-center font-medium ${isError ? "text-red-400" : "text-white/40"}`}>
          {label}
        </span>
        {isError && (
          <span className="flex items-center gap-0.5 text-[10px] text-red-400 bg-red-500/10 border border-red-500/25 rounded px-1.5 py-0.5 font-medium">
            <XCircle className="w-2.5 h-2.5" /> Error
          </span>
        )}
      </div>
      <button
        onClick={onClick}
        className={`relative w-full aspect-video bg-white/5 rounded-lg overflow-hidden group transition-all ${
          isError
            ? "ring-1 ring-red-500/40 hover:ring-red-500/60"
            : "hover:ring-2 hover:ring-white/30"
        }`}
      >
        <img
          src={url}
          alt={label}
          className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
        />
        {isError && (
          <div className="absolute top-1.5 left-1.5 flex items-center gap-1 bg-red-600/90 rounded px-1.5 py-0.5">
            <XCircle className="w-2.5 h-2.5 text-white" />
            <span className="text-white text-[10px] font-semibold">Step failed here</span>
          </div>
        )}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100">
          <ZoomIn className="w-6 h-6 text-white drop-shadow-lg" />
        </div>
      </button>
    </div>
  )
}

function EmptyThumb({ label }: { label: string }) {
  return (
    <div className="space-y-1.5">
      <div className="text-white/20 text-xs text-center">{label}</div>
      <div className="w-full aspect-video bg-white/[0.02] rounded-lg border border-dashed border-white/10 flex items-center justify-center">
        <ImageIcon className="w-5 h-5 text-white/10" />
      </div>
    </div>
  )
}

function Lightbox({ url, onClose }: { url: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-6"
      onClick={onClose}
    >
      <button
        onClick={onClose}
        className="absolute top-4 right-4 text-white/60 hover:text-white p-2 rounded-full bg-white/10 hover:bg-white/20 transition-colors"
      >
        <X className="w-5 h-5" />
      </button>
      <img
        src={url}
        alt="Screenshot"
        className="max-w-full max-h-[90vh] object-contain rounded-xl shadow-2xl"
        onClick={e => e.stopPropagation()}
      />
    </div>
  )
}

function ItemCard({ item }: { item: BulkItem }) {
  const [shots, setShots] = useState<string[]>([])
  const [loadingShots, setLoadingShots] = useState(false)
  const [lightbox, setLightbox] = useState<string | null>(null)

  useEffect(() => {
    if (!item.execution_id) return
    if (item.status !== "success" && item.status !== "failed") return
    setLoadingShots(true)
    executionApi.screenshots(item.execution_id)
      .then(r => {
        const all: string[] = r.data.screenshots ?? []
        // ss_NNN.png are auto-duplicates of the named screenshots taken in the same step.
        // Filter them out so the 3 columns map to the meaningful named captures:
        //   Before Data → search-result.png
        //   Payment     → receipt.png
        //   After Data  → updated-balance.png
        const named = all.filter(s => !/^ss_\d+\.png$/i.test(s))
        setShots(named.length > 0 ? named : all)
      })
      .catch(() => {})
      .finally(() => setLoadingShots(false))
  }, [item.execution_id, item.status])

  const shotUrl = (filename: string) =>
    `${API_URL}/api/execution/screenshot/${item.execution_id}/${filename}`

  const borderColor = {
    success: "border-green-500/20",
    failed:  "border-red-500/20",
    running: "border-white/10",
    pending: "border-white/5",
  }[item.status] ?? "border-white/5"

  const bgColor = {
    success: "bg-green-500/[0.04]",
    failed:  "bg-red-500/[0.04]",
    running: "bg-white/[0.03]",
    pending: "bg-white/[0.02]",
  }[item.status] ?? "bg-white/[0.02]"

  const statusIcon = {
    success: <CheckCircle2 className="w-5 h-5 text-green-400 shrink-0" />,
    failed:  <XCircle className="w-5 h-5 text-red-400/80 shrink-0" />,
    running: <Loader2 className="w-5 h-5 text-white/50 animate-spin shrink-0" />,
    pending: <Clock className="w-5 h-5 text-white/20 shrink-0" />,
  }[item.status]

  const statusLabel = {
    success: <span className="text-green-400 text-xs font-semibold">Success</span>,
    failed:  <span className="text-red-400/70 text-xs font-semibold">Failed</span>,
    running: <span className="text-white/50 text-xs font-semibold">Running</span>,
    pending: <span className="text-white/20 text-xs">Pending</span>,
  }[item.status]

  return (
    <>
      <div className={`border ${borderColor} ${bgColor} rounded-xl overflow-hidden`}>
        {/* Row header */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 px-5 py-3 border-b border-white/5">
          <div className="flex items-center gap-2.5 flex-1 min-w-0">
            {statusIcon}
            <span className="font-mono text-sm text-white font-medium truncate">{item.number}</span>
            {item.label && item.label !== item.number && (
              <span className="text-white/30 text-xs shrink-0">{item.label}</span>
            )}
          </div>
          <div className="flex items-center gap-5 text-xs text-white/40 shrink-0">
            {item.started_at && (
              <div className="flex flex-col items-end">
                <span className="text-white/20 text-[10px] uppercase tracking-wide">Started</span>
                <span>{new Date(item.started_at).toLocaleTimeString()}</span>
              </div>
            )}
            {item.finished_at && (
              <div className="flex flex-col items-end">
                <span className="text-white/20 text-[10px] uppercase tracking-wide">Finished</span>
                <span>{new Date(item.finished_at).toLocaleTimeString()}</span>
              </div>
            )}
            {item.duration_seconds != null && (
              <div className="flex flex-col items-end">
                <span className="text-white/20 text-[10px] uppercase tracking-wide">Duration</span>
                <span className="text-white/60">{formatDuration(item.duration_seconds)}</span>
              </div>
            )}
            <div className="flex flex-col items-center">
              <span className="text-white/20 text-[10px] uppercase tracking-wide">Status</span>
              {statusLabel}
            </div>
            {item.execution_id && (
              <Link
                href={`/execution/${item.execution_id}`}
                className="flex items-center gap-1 text-white/30 hover:text-white transition-colors"
              >
                Detail <ChevronRight className="w-3 h-3" />
              </Link>
            )}
          </div>
        </div>

        {/* SUCCESS / FAILED: same 3-column screenshot grid */}
        {(item.status === "success" || item.status === "failed") && (
          <div className="p-5 space-y-3">
            {/* Error message banner */}
            {item.status === "failed" && item.error && (
              <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-2.5">
                <XCircle className="w-3.5 h-3.5 text-red-400/70 mt-0.5 shrink-0" />
                <p className="text-red-400/70 text-xs font-mono leading-relaxed">{item.error}</p>
              </div>
            )}

            {loadingShots ? (
              <div className="flex items-center justify-center py-10 gap-2 text-white/20 text-xs">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading screenshots…
              </div>
            ) : (() => {
              // Split screenshots into named (success checkpoints) and error shots
              const namedShots = shots.filter(s => !isErrorShot(s))
              const errorShots = shots.filter(s => isErrorShot(s))

              return (
                <div className="space-y-4">
                  {/* Error screenshots — shown first with red styling for immediate visibility */}
                  {errorShots.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-red-400/60 text-[10px] uppercase tracking-widest font-semibold">
                        Failure Screenshot
                      </p>
                      <div className={`grid gap-4 ${errorShots.length === 1 ? "grid-cols-1 max-w-sm" : "grid-cols-2"}`}>
                        {errorShots.map(shot => (
                          <ScreenshotThumb
                            key={shot}
                            url={shotUrl(shot)}
                            label={errorStepLabel(shot)}
                            isError
                            onClick={() => setLightbox(shotUrl(shot))}
                          />
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Named checkpoint screenshots (search-result, receipt, updated-balance) */}
                  {namedShots.length > 0 && (
                    <div className="space-y-2">
                      {errorShots.length > 0 && (
                        <p className="text-white/20 text-[10px] uppercase tracking-widest font-semibold">
                          Progress Screenshots
                        </p>
                      )}
                      <div className="grid grid-cols-3 gap-4">
                        {SHOT_LABELS.map((label, i) => {
                          const shot = namedShots[i]
                          return shot ? (
                            <ScreenshotThumb
                              key={shot}
                              url={shotUrl(shot)}
                              label={label}
                              onClick={() => setLightbox(shotUrl(shot))}
                            />
                          ) : (
                            <EmptyThumb key={label} label={label} />
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* No screenshots at all */}
                  {shots.length === 0 && item.status === "failed" && (
                    <p className="text-white/20 text-xs">No screenshot captured</p>
                  )}
                </div>
              )
            })()}
          </div>
        )}

        {/* RUNNING */}
        {item.status === "running" && (
          <div className="flex items-center justify-center gap-2 py-10 text-white/30 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> In progress…
          </div>
        )}

        {/* PENDING */}
        {item.status === "pending" && (
          <div className="flex items-center justify-center py-10 text-white/20 text-sm">
            Waiting to start
          </div>
        )}
      </div>

      {lightbox && (
        <Lightbox url={lightbox} onClose={() => setLightbox(null)} />
      )}
    </>
  )
}

export default function BulkResultPage() {
  const { id } = useParams<{ id: string }>()
  const [bulk, setBulk] = useState<BulkRun | null>(null)
  const [loading, setLoading] = useState(true)
  const pollRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    bulkApi.get(id)
      .then(r => setBulk(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    if (!bulk || bulk.status === "completed") {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await bulkApi.get(id)
        setBulk(data)
        if (data.status === "completed") clearInterval(pollRef.current!)
      } catch {}
    }, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [id, bulk?.status])

  const progress = bulk ? Math.round((bulk.completed / bulk.total) * 100) : 0

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Bulk Results" />
        <main className="flex-1 p-8">

          {loading ? (
            <div className="flex items-center justify-center h-64 text-white/30">
              <Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading…
            </div>
          ) : !bulk ? (
            <div className="flex flex-col items-center justify-center h-64 gap-3">
              <p className="text-white/30 text-sm">Bulk run not found</p>
              <Link href="/bulk" className="text-white/50 hover:text-white text-xs underline transition-colors">
                Back to Bulk
              </Link>
            </div>
          ) : (
            <div className="max-w-5xl mx-auto space-y-6">

              {/* Back */}
              <Link
                href="/bulk"
                className="inline-flex items-center gap-1.5 text-white/30 hover:text-white text-sm transition-colors"
              >
                <ArrowLeft className="w-4 h-4" /> Back to Bulk
              </Link>

              {/* Summary card */}
              <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5 space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h1 className="text-white font-semibold text-lg">{bulk.flow_name}</h1>
                    <p className="text-white/30 text-xs mt-1">
                      {bulk.completed}/{bulk.total} completed
                    </p>
                  </div>
                  <span className={`shrink-0 text-xs px-3 py-1 rounded-full border font-medium ${
                    bulk.status === "running"
                      ? "text-white/60 border-white/20 bg-white/5"
                      : bulk.failed === 0
                        ? "text-green-400 border-green-400/30 bg-green-400/10"
                        : "text-orange-400 border-orange-400/30 bg-orange-400/10"
                  }`}>
                    {bulk.status === "running"
                      ? `Running ${bulk.completed}/${bulk.total}`
                      : bulk.failed === 0
                        ? "All Passed"
                        : `${bulk.failed} Failed`}
                  </span>
                </div>

                {/* Progress bar */}
                <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${
                      bulk.status === "completed"
                        ? bulk.failed === 0 ? "bg-green-400/70" : "bg-orange-400/70"
                        : "bg-white/50"
                    }`}
                    style={{ width: `${progress}%` }}
                  />
                </div>

                {/* Stat pills */}
                <div className="flex items-center gap-5">
                  <div className="flex items-center gap-1.5 text-xs text-white/40">
                    <CheckCircle2 className="w-3.5 h-3.5 text-green-400/70" />
                    <span>{bulk.success} passed</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-white/40">
                    <XCircle className="w-3.5 h-3.5 text-red-400/60" />
                    <span>{bulk.failed} failed</span>
                  </div>
                  {bulk.status === "running" && (
                    <div className="flex items-center gap-1.5 text-xs text-white/30">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>{bulk.total - bulk.completed} pending</span>
                    </div>
                  )}
                  {bulk.started_at && (
                    <div className="ml-auto text-white/20 text-xs">
                      Started {new Date(bulk.started_at).toLocaleString()}
                    </div>
                  )}
                </div>
              </div>

              {/* Item cards */}
              <div className="space-y-4">
                {bulk.items.map((item, i) => (
                  <ItemCard key={i} item={item} />
                ))}
              </div>

            </div>
          )}
        </main>
      </div>
    </div>
  )
}

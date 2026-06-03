"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { useParams, useRouter } from "next/navigation"
import { executionApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { Execution, ExecutionLog, WSMessage } from "@/types"
import { formatDate, formatDuration, statusColor, logColor } from "@/lib/utils"
import { cn } from "@/lib/utils"
import {
  Loader2, Ban, RefreshCw, Camera, Terminal,
  Monitor, Image as ImageIcon, Maximize2, X
} from "lucide-react"

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000"

export default function ExecutionViewerPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  const [exec, setExec]           = useState<Execution | null>(null)
  const [logs, setLogs]           = useState<ExecutionLog[]>([])
  const [screenshots, setScreenshots] = useState<string[]>([])
  const [liveFrame, setLiveFrame] = useState<string | null>(null)
  const [selectedShot, setSelectedShot] = useState<string | null>(null)
  const [tab, setTab]             = useState<"live" | "logs" | "screenshots">("live")
  const [loading, setLoading]     = useState(true)
  const [cancelling, setCancelling] = useState(false)
  const [wsConnected, setWsConnected] = useState(false)
  const [liveFullscreen, setLiveFullscreen] = useState(false)

  const logsEndRef  = useRef<HTMLDivElement>(null)
  const wsRef       = useRef<WebSocket | null>(null)
  const pingRef     = useRef<NodeJS.Timeout | null>(null)
  const logsRef     = useRef<ExecutionLog[]>([])

  // Keep logsRef in sync
  useEffect(() => { logsRef.current = logs }, [logs])

  // ── Initial load ─────────────────────────────────────────────────────
  useEffect(() => {
    executionApi.get(id).then(r => {
      setExec(r.data)
      setLogs(r.data.logs || [])
      setScreenshots(r.data.screenshots || [])
      const isRunning = ["running", "pending"].includes(r.data.status)
      setTab(isRunning ? "live" : "logs")
    }).finally(() => setLoading(false))
  }, [id, router])

  // ── WebSocket ─────────────────────────────────────────────────────────
  const connectWS = useCallback(() => {
    const url = `${WS_URL}/api/execution/ws/${id}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setWsConnected(true)
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send("ping")
      }, 25000)
    }

    ws.onmessage = (evt) => {
      if (evt.data === "pong" || evt.data === "ping") return
      try {
        const msg: WSMessage = JSON.parse(evt.data)

        if (msg.type === "log") {
          const log = msg.data as unknown as ExecutionLog
          setLogs(prev => [...prev, log])
        }

        if (msg.type === "live_frame") {
          setLiveFrame((msg.data as { b64: string }).b64)
          // Switch to live tab automatically when frames arrive
          setTab(prev => prev === "screenshots" ? prev : "live")
        }

        if (msg.type === "screenshot") {
          const fn = (msg.data as { filename: string }).filename
          setScreenshots(prev => prev.includes(fn) ? prev : [...prev, fn])
        }

        if (msg.type === "status") {
          const st = (msg.data as { status: string }).status
          setExec(prev => prev ? { ...prev, status: st as any } : prev)
          if (["success", "failed", "cancelled"].includes(st)) {
            setLiveFrame(null)
            setTab("logs")
          }
        }

        if (msg.type === "complete") {
          setExec(prev => prev ? { ...prev, ...(msg.data as Partial<Execution>) } : prev)
          setLiveFrame(null)
          setTab("logs")
        }
      } catch {}
    }

    ws.onclose = () => {
      setWsConnected(false)
      if (pingRef.current) clearInterval(pingRef.current)
    }
  }, [id])

  useEffect(() => {
    connectWS()
    return () => {
      wsRef.current?.close()
      if (pingRef.current) clearInterval(pingRef.current)
    }
  }, [connectWS])

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [logs])

  // ── Actions ───────────────────────────────────────────────────────────
  const cancel = async () => {
    setCancelling(true)
    try { await executionApi.cancel(id) } finally { setCancelling(false) }
  }

  const refresh = async () => {
    const r = await executionApi.get(id)
    setExec(r.data)
    setLogs(r.data.logs || [])
    setScreenshots(r.data.screenshots || [])
  }

  if (loading) {
    return (
      <div className="flex min-h-screen bg-black">
        <Sidebar />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="animate-spin text-white/20" />
        </div>
      </div>
    )
  }

  if (!exec) return null

  const isRunning = ["running", "pending"].includes(exec.status)
  const progress = exec.steps_total > 0 ? (exec.steps_completed / exec.steps_total) * 100 : 0
  const hasLive = !!liveFrame && isRunning

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header title="Execution Viewer" />

        <main className="flex-1 p-6 space-y-5 overflow-auto">

          {/* ── Execution Info ── */}
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 flex-wrap">
                  <h2 className="text-white font-semibold text-base">{exec.flow_name}</h2>
                  <span className={cn("text-xs px-2.5 py-1 rounded border", statusColor(exec.status))}>
                    {exec.status}
                  </span>
                  {isRunning && wsConnected && (
                    <span className="flex items-center gap-1.5 text-xs text-white/40">
                      <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse2 inline-block" />
                      Live
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-4 gap-4 mt-4">
                  {[
                    { label: "Started", value: formatDate(exec.started_at) },
                    { label: "Duration", value: formatDuration(exec.duration_seconds) },
                    { label: "Steps", value: `${exec.steps_completed}/${exec.steps_total}` },
                    { label: "Screenshots", value: String(screenshots.length) },
                  ].map(({ label, value }) => (
                    <div key={label}>
                      <div className="text-white/30 text-xs">{label}</div>
                      <div className="text-white text-sm mt-0.5">{value}</div>
                    </div>
                  ))}
                </div>

                {exec.steps_total > 0 && (
                  <div className="mt-3">
                    <div className="h-1 bg-white/10 rounded-full max-w-sm">
                      <div
                        className="h-1 bg-white rounded-full transition-all duration-700"
                        style={{ width: `${Math.min(progress, 100)}%` }}
                      />
                    </div>
                  </div>
                )}

                {exec.result_summary && (
                  <div className="mt-3 text-white/50 text-sm">{exec.result_summary}</div>
                )}
                {exec.error && (
                  <div className="mt-3 text-white/40 text-xs bg-white/5 px-3 py-2 rounded-lg border border-white/10 font-mono">
                    ⚠ {exec.error}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button onClick={refresh}
                  className="p-1.5 text-white/30 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
                  <RefreshCw className="w-4 h-4" />
                </button>
                {isRunning && (
                  <button onClick={cancel} disabled={cancelling}
                    className="flex items-center gap-1.5 border border-white/20 text-white/60 hover:text-white px-3 py-1.5 rounded-lg text-sm transition-colors disabled:opacity-50">
                    {cancelling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
                    Cancel
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* ── Tabs ── */}
          <div className="flex gap-2">
            {[
              { key: "live",        label: "Live Browser", icon: Monitor,   badge: hasLive ? "●" : undefined, pulse: hasLive },
              { key: "logs",        label: "Logs",         icon: Terminal,  badge: String(logs.length) },
              { key: "screenshots", label: "Screenshots",  icon: Camera,    badge: String(screenshots.length) },
            ].map(({ key, label, icon: Icon, badge, pulse }) => (
              <button key={key} onClick={() => setTab(key as any)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all border",
                  tab === key
                    ? "bg-white text-black border-white font-medium"
                    : "text-white/40 border-white/10 hover:text-white hover:border-white/20"
                )}>
                <Icon className="w-4 h-4" />
                {label}
                {badge !== undefined && (
                  <span className={cn(
                    "text-xs px-1.5 py-0.5 rounded min-w-[20px] text-center",
                    tab === key ? "bg-black/20" : "bg-white/10",
                    pulse && "animate-pulse2"
                  )}>{badge}</span>
                )}
              </button>
            ))}
          </div>

          {/* ── LIVE BROWSER VIEW ── */}
          {tab === "live" && (
            <div className="relative">
              {hasLive ? (
                <div className="bg-black border border-white/15 rounded-xl overflow-hidden">
                  {/* Browser chrome bar */}
                  <div className="flex items-center gap-3 px-4 py-2.5 border-b border-white/10 bg-white/[0.03]">
                    <div className="flex gap-1.5">
                      <div className="w-2.5 h-2.5 rounded-full bg-white/10" />
                      <div className="w-2.5 h-2.5 rounded-full bg-white/10" />
                      <div className="w-2.5 h-2.5 rounded-full bg-white/10" />
                    </div>
                    <div className="flex-1 bg-white/5 rounded px-3 py-1 text-white/30 text-xs font-mono">
                      AI Agent — Live View
                    </div>
                    <div className="flex items-center gap-1.5 text-white/40 text-xs">
                      <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse2 inline-block" />
                      Streaming
                    </div>
                    <button
                      onClick={() => setLiveFullscreen(true)}
                      className="p-1 text-white/30 hover:text-white transition-colors"
                    >
                      <Maximize2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  {/* Live frame */}
                  <img
                    src={`data:image/jpeg;base64,${liveFrame}`}
                    alt="Live browser"
                    className="w-full block"
                    style={{ imageRendering: "crisp-edges" }}
                  />
                </div>
              ) : (
                <div className="bg-white/[0.02] border border-white/10 rounded-xl flex flex-col items-center justify-center py-24 gap-4">
                  <Monitor className="w-12 h-12 text-white/10" />
                  <div className="text-white/20 text-sm">
                    {isRunning
                      ? "Browser starting… live view will appear momentarily"
                      : "No live view — execution is not running"}
                  </div>
                  {isRunning && (
                    <Loader2 className="w-5 h-5 text-white/20 animate-spin" />
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── LOGS ── */}
          {tab === "logs" && (
            <div className="bg-black border border-white/10 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2 border-b border-white/5 bg-white/[0.02]">
                <div className="flex items-center gap-2">
                  <div className="flex gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full bg-white/10" />
                    <div className="w-2.5 h-2.5 rounded-full bg-white/10" />
                    <div className="w-2.5 h-2.5 rounded-full bg-white/10" />
                  </div>
                  <span className="text-white/20 text-xs font-mono">execution.log</span>
                </div>
                {isRunning && <span className="w-2 h-2 rounded-full bg-white animate-pulse2 block" />}
              </div>
              <div className="h-[500px] overflow-y-auto p-4 log-terminal">
                {logs.length === 0 && (
                  <div className="text-white/20 text-sm">Waiting for logs…</div>
                )}
                {logs.map((log, i) => (
                  <div key={i} className={cn("flex gap-3 mb-0.5 animate-fade-in text-xs leading-relaxed", logColor(log.level))}>
                    <span className="text-white/20 shrink-0 select-none tabular-nums">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>
                    <span className="break-all">{log.message}</span>
                  </div>
                ))}
                {isRunning && (
                  <span className="text-white/20 text-xs blink">▌</span>
                )}
                <div ref={logsEndRef} />
              </div>
            </div>
          )}

          {/* ── SCREENSHOTS ── */}
          {tab === "screenshots" && (
            <div>
              {screenshots.length === 0 ? (
                <div className="text-center py-20 text-white/20 text-sm">
                  <ImageIcon className="w-8 h-8 mx-auto mb-3 opacity-20" />
                  No screenshots yet
                </div>
              ) : (
                <div className="grid grid-cols-3 xl:grid-cols-4 gap-3">
                  {screenshots.map((shot, i) => (
                    <button key={i} onClick={() => setSelectedShot(shot)}
                      className="relative aspect-video bg-white/5 border border-white/10 rounded-lg overflow-hidden hover:border-white/30 transition-all group">
                      <img
                        src={executionApi.screenshotUrl(exec.id, shot)}
                        alt={`Step ${i + 1}`}
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      />
                      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors" />
                      <div className="absolute bottom-1.5 left-1.5 text-white/60 text-[10px] font-mono bg-black/70 px-1.5 py-0.5 rounded">
                        {i + 1}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

        </main>
      </div>

      {/* ── Lightbox ── */}
      {selectedShot && (
        <div className="fixed inset-0 bg-black/95 flex items-center justify-center z-50 p-8"
          onClick={() => setSelectedShot(null)}>
          <img
            src={executionApi.screenshotUrl(exec.id, selectedShot)}
            alt="Screenshot"
            className="max-w-full max-h-full rounded-xl border border-white/10"
          />
        </div>
      )}

      {/* ── Live Fullscreen ── */}
      {liveFullscreen && liveFrame && (
        <div className="fixed inset-0 bg-black z-50 flex flex-col">
          <div className="flex items-center justify-between px-6 py-3 border-b border-white/10">
            <div className="flex items-center gap-2 text-white/50 text-sm">
              <span className="w-2 h-2 bg-white rounded-full animate-pulse2 inline-block" />
              Live Browser — {exec.flow_name}
            </div>
            <button onClick={() => setLiveFullscreen(false)}
              className="p-2 text-white/30 hover:text-white hover:bg-white/5 rounded-lg transition-colors">
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="flex-1 flex items-center justify-center p-4">
            <img
              src={`data:image/jpeg;base64,${liveFrame}`}
              alt="Live browser fullscreen"
              className="max-w-full max-h-full object-contain rounded-lg"
              style={{ imageRendering: "crisp-edges" }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { bulkApi, diskFlowsApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { BulkRun, DiskFlow } from "@/types"
import { formatDuration } from "@/lib/utils"
import {
  Upload, Play, CheckCircle2, XCircle, Loader2,
  Clock, ChevronRight, Layers
} from "lucide-react"

export default function BulkPage() {
  const router = useRouter()
  const fileRef = useRef<HTMLInputElement>(null)

  const [flows, setFlows] = useState<DiskFlow[]>([])
  const [selectedFlow, setSelectedFlow] = useState("")
  const [numbers, setNumbers] = useState<string[]>([])
  const [fileName, setFileName] = useState("")
  const [variableNames, setVariableNames] = useState("MISTIN_ID, PHONE_NUMBER, MOBILE_NUMBER")
  const [maxParallel, setMaxParallel] = useState(3)
  const [running, setRunning] = useState(false)
  const [activeBulk, setActiveBulk] = useState<BulkRun | null>(null)
  const [history, setHistory] = useState<BulkRun[]>([])
  const pollRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    diskFlowsApi.list().then(r => {
      setFlows(r.data)
      if (r.data.length > 0) setSelectedFlow(r.data[0].id)
    })
    bulkApi.list().then(r => setHistory(r.data)).catch(() => {})
  }, [])

  // Poll active run
  useEffect(() => {
    if (!activeBulk || activeBulk.status === "completed") {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await bulkApi.get(activeBulk.id)
        setActiveBulk(data)
        if (data.status === "completed") {
          setRunning(false)
          bulkApi.list().then(r => setHistory(r.data)).catch(() => {})
        }
      } catch {}
    }, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [activeBulk?.id, activeBulk?.status])

  const onFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFileName(file.name)
    const reader = new FileReader()
    reader.onload = ev => {
      const text = ev.target?.result as string
      const parsed = text.split(/[\n,]+/).map(l => l.trim()).filter(Boolean)
      setNumbers(parsed)
    }
    reader.readAsText(file)
  }

  const handleStart = async () => {
    if (!selectedFlow || numbers.length === 0) return
    setRunning(true)
    const varNames = variableNames.split(",").map(v => v.trim()).filter(Boolean)
    try {
      const { data } = await bulkApi.run({
        flow_id: selectedFlow,
        numbers,
        variable_names: varNames,
        max_parallel: maxParallel,
      })
      setActiveBulk(data)
    } catch {
      setRunning(false)
    }
  }

  const statusIcon = (s: string) => {
    if (s === "success")  return <CheckCircle2 className="w-4 h-4 text-green-400" />
    if (s === "failed")   return <XCircle className="w-4 h-4 text-red-400/70" />
    if (s === "running")  return <Loader2 className="w-4 h-4 text-white/60 animate-spin" />
    return <Clock className="w-4 h-4 text-white/20" />
  }

  const statusText = (s: string) => {
    if (s === "success") return "text-green-400"
    if (s === "failed")  return "text-red-400/70"
    if (s === "running") return "text-white/60"
    return "text-white/20"
  }

  const progress = activeBulk ? Math.round((activeBulk.completed / activeBulk.total) * 100) : 0

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Bulk Run" />
        <main className="flex-1 p-8 space-y-6">

          <div className="grid grid-cols-3 gap-6">

            {/* ── Config Panel ── */}
            <div className="col-span-1 space-y-4">
              <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5 space-y-4">
                <h2 className="text-white text-sm font-semibold flex items-center gap-2">
                  <Layers className="w-4 h-4 text-white/40" /> Configuration
                </h2>

                {/* Flow select */}
                <div className="space-y-1.5">
                  <label className="text-white/40 text-xs">Flow</label>
                  <select
                    value={selectedFlow}
                    onChange={e => setSelectedFlow(e.target.value)}
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-white/30"
                  >
                    {flows.map(f => (
                      <option key={f.id} value={f.id} className="bg-black">{f.name}</option>
                    ))}
                  </select>
                </div>

                {/* File upload */}
                <div className="space-y-1.5">
                  <label className="text-white/40 text-xs">Numbers File (.txt)</label>
                  <input ref={fileRef} type="file" accept=".txt,.csv" onChange={onFileUpload} className="hidden" />
                  <button
                    onClick={() => fileRef.current?.click()}
                    className="w-full flex items-center gap-2 bg-white/5 border border-white/10 border-dashed rounded-lg px-3 py-3 text-white/40 hover:text-white hover:border-white/30 transition-colors text-sm"
                  >
                    <Upload className="w-4 h-4" />
                    {fileName || "Upload .txt — one number per line"}
                  </button>
                  {numbers.length > 0 && (
                    <p className="text-white/30 text-xs">{numbers.length} numbers loaded</p>
                  )}
                </div>

                {/* Variable names */}
                <div className="space-y-1.5">
                  <label className="text-white/40 text-xs">Variable Names (comma separated)</label>
                  <input
                    value={variableNames}
                    onChange={e => setVariableNames(e.target.value)}
                    placeholder="MISTIN_ID, PHONE_NUMBER"
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-white/30 placeholder:text-white/20"
                  />
                  <p className="text-white/20 text-xs">Each number replaces all these variables</p>
                </div>

                {/* Max parallel */}
                <div className="space-y-1.5">
                  <label className="text-white/40 text-xs">Max Parallel Runs: {maxParallel}</label>
                  <input
                    type="range" min={1} max={5} value={maxParallel}
                    onChange={e => setMaxParallel(Number(e.target.value))}
                    className="w-full accent-white"
                  />
                  <div className="flex justify-between text-white/20 text-xs">
                    <span>1</span><span>5</span>
                  </div>
                </div>

                {/* Start button */}
                <button
                  onClick={handleStart}
                  disabled={running || numbers.length === 0 || !selectedFlow}
                  className="w-full flex items-center justify-center gap-2 bg-white text-black font-medium text-sm py-2.5 rounded-lg hover:bg-white/90 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  {running
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> Running...</>
                    : <><Play className="w-4 h-4" /> Start Bulk Run</>
                  }
                </button>
              </div>

              {/* History */}
              {history.length > 0 && (
                <div className="bg-white/[0.03] border border-white/10 rounded-xl p-4 space-y-2">
                  <h3 className="text-white/40 text-xs uppercase tracking-widest">History</h3>
                  {history.slice(0, 5).map(h => (
                    <button
                      key={h.id}
                      onClick={() => setActiveBulk(h)}
                      className="w-full flex items-center justify-between py-2 border-b border-white/5 last:border-0 hover:text-white text-white/50 text-xs transition-colors"
                    >
                      <span className="truncate max-w-[120px]">{h.flow_name}</span>
                      <span>{h.success}/{h.total} ok</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* ── Results Panel ── */}
            <div className="col-span-2">
              {!activeBulk ? (
                <div className="h-full flex items-center justify-center border border-white/5 rounded-xl">
                  <div className="text-center text-white/20">
                    <Layers className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p className="text-sm">Upload a file and start a bulk run</p>
                  </div>
                </div>
              ) : (
                <div className="bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden">

                  {/* Header */}
                  <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between">
                    <div>
                      <div className="text-white font-semibold text-sm">{activeBulk.flow_name}</div>
                      <div className="text-white/30 text-xs mt-0.5">
                        {activeBulk.completed}/{activeBulk.total} completed
                        · {activeBulk.success} success · {activeBulk.failed} failed
                      </div>
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded border ${
                      activeBulk.status === "completed"
                        ? "text-green-400 border-green-400/30 bg-green-400/10"
                        : "text-white/60 border-white/20 bg-white/5"
                    }`}>
                      {activeBulk.status === "running"
                        ? `Running ${activeBulk.completed}/${activeBulk.total}`
                        : "Completed"}
                    </span>
                  </div>

                  {/* Progress bar */}
                  {activeBulk.status === "running" && (
                    <div className="h-0.5 bg-white/5">
                      <div
                        className="h-full bg-white/60 transition-all duration-500"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  )}

                  {/* Table */}
                  <div className="divide-y divide-white/5 max-h-[520px] overflow-y-auto">
                    {activeBulk.items.map((item, i) => (
                      <div key={i} className="flex items-center justify-between px-5 py-3 hover:bg-white/[0.02]">
                        <div className="flex items-center gap-3 min-w-0">
                          {statusIcon(item.status)}
                          <span className={`text-sm font-mono ${statusText(item.status)}`}>
                            {item.number}
                          </span>
                        </div>
                        <div className="flex items-center gap-4 shrink-0">
                          {item.duration_seconds != null && (
                            <span className="text-white/30 text-xs">
                              {formatDuration(item.duration_seconds)}
                            </span>
                          )}
                          {item.error && (
                            <span className="text-red-400/50 text-xs truncate max-w-[160px]" title={item.error}>
                              {item.error}
                            </span>
                          )}
                          {item.execution_id && (
                            <Link
                              href={`/execution/${item.execution_id}`}
                              className="flex items-center gap-1 text-white/30 hover:text-white text-xs transition-colors"
                            >
                              View <ChevronRight className="w-3 h-3" />
                            </Link>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>

                </div>
              )}
            </div>
          </div>

        </main>
      </div>
    </div>
  )
}

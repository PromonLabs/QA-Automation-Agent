"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { bulkApi, diskFlowsApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { BulkRun, DiskFlow } from "@/types"
import { formatDuration } from "@/lib/utils"
import {
  Play, CheckCircle2, XCircle, Loader2, Clock,
  ChevronRight, Layers, Settings2, Plus, Trash2,
  Save, ChevronDown, ChevronUp,
} from "lucide-react"

export default function BulkPage() {
  const [flows, setFlows]               = useState<DiskFlow[]>([])
  const [selectedFlow, setSelectedFlow] = useState("")
  const [numbersInput, setNumbersInput] = useState("")
  const [maxParallel, setMaxParallel]   = useState(1)
  const [running, setRunning]           = useState(false)
  const [activeBulk, setActiveBulk]     = useState<BulkRun | null>(null)
  const [history, setHistory]           = useState<BulkRun[]>([])
  const pollRef = useRef<NodeJS.Timeout | null>(null)

  // Bulk env
  const [envOpen, setEnvOpen]     = useState(false)
  const [envRows, setEnvRows]     = useState<{ key: string; value: string }[]>([])
  const [envSaving, setEnvSaving] = useState(false)
  const [envSaved, setEnvSaved]   = useState(false)

  useEffect(() => {
    diskFlowsApi.list().then(r => {
      setFlows(r.data)
      if (r.data.length > 0) setSelectedFlow(r.data[0].id)
    })
    bulkApi.list().then(r => setHistory(r.data)).catch(() => {})
    bulkApi.getEnv().then(r => {
      const parsed = Object.entries(r.data).map(([key, value]) => ({ key, value }))
      setEnvRows(parsed.length ? parsed : [{ key: "", value: "" }])
    }).catch(() => setEnvRows([{ key: "", value: "" }]))
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

  const parsedNumbers = numbersInput
    .split(/[\n,]+/)
    .map(n => n.trim())
    .filter(Boolean)

  const addEnvRow = () => setEnvRows(r => [...r, { key: "", value: "" }])
  const removeEnvRow = (i: number) => setEnvRows(r => r.filter((_, idx) => idx !== i))
  const updateEnvRow = (i: number, field: "key" | "value", val: string) =>
    setEnvRows(r => r.map((row, idx) => idx === i ? { ...row, [field]: val } : row))

  const saveEnv = async () => {
    setEnvSaving(true)
    const env_vars = Object.fromEntries(
      envRows.filter(r => r.key.trim()).map(r => [r.key.trim(), r.value])
    )
    await bulkApi.saveEnv(env_vars).catch(() => {})
    setEnvSaving(false)
    setEnvSaved(true)
    setTimeout(() => setEnvSaved(false), 2000)
  }

  // Parse a single number entry into env vars.
  // 9-digit number (e.g. 299547643): MISTIN_ID = full, rest = last 6
  // 6-digit number (e.g. 547643):    all four = same value
  const toEnvVars = (n: string) => {
    const digits = n.replace(/\D/g, "")
    const last6  = digits.slice(-6)
    // COS search needs full 9-digit number — if user typed 6 digits, prepend "299"
    const mistin = digits.length <= 6 ? "299" + digits : digits
    return {
      MISTIN_ID:      mistin,
      ACCOUNT_NUMBER: last6,
      PHONE_NUMBER:   last6,
      MOBILE_NUMBER:  last6,
    }
  }

  const handleStart = async () => {
    if (!selectedFlow || parsedNumbers.length === 0) return
    setRunning(true)
    try {
      const { data } = await bulkApi.run({
        flow_id: selectedFlow,
        max_parallel: maxParallel,
        subscribers: parsedNumbers.map(n => ({
          env_vars: toEnvVars(n),
          label: n.replace(/\D/g, "").slice(-6),  // show last 6 in results table
        })),
      })
      setActiveBulk(data)
    } catch {
      setRunning(false)
    }
  }

  const statusIcon = (s: string) => {
    if (s === "success") return <CheckCircle2 className="w-4 h-4 text-green-400" />
    if (s === "failed")  return <XCircle className="w-4 h-4 text-red-400/70" />
    if (s === "running") return <Loader2 className="w-4 h-4 text-white/60 animate-spin" />
    return <Clock className="w-4 h-4 text-white/20" />
  }

  const statusText = (s: string) => {
    if (s === "success") return "text-green-400"
    if (s === "failed")  return "text-red-400/70"
    if (s === "running") return "text-white/60"
    return "text-white/20"
  }

  const progress = activeBulk
    ? Math.round((activeBulk.completed / activeBulk.total) * 100)
    : 0

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Bulk Run" />
        <main className="flex-1 p-8 space-y-6">
          <div className="grid grid-cols-3 gap-6">

            {/* ── Left column ── */}
            <div className="col-span-1 space-y-4">

              {/* Config */}
              <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5 space-y-4">
                <h2 className="text-white text-sm font-semibold flex items-center gap-2">
                  <Layers className="w-4 h-4 text-white/40" /> Configuration
                </h2>

                {/* Flow */}
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

                {/* Numbers input */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-white/40 text-xs">Numbers</label>
                    {parsedNumbers.length > 0 && (
                      <span className="text-white/30 text-xs">{parsedNumbers.length} numbers</span>
                    )}
                  </div>
                  <textarea
                    value={numbersInput}
                    onChange={e => setNumbersInput(e.target.value)}
                    placeholder={"562617, 547643, 223401\nor one per line"}
                    rows={4}
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm font-mono focus:outline-none focus:border-white/30 placeholder:text-white/20 resize-none"
                  />
                  <p className="text-white/20 text-xs">Comma or newline separated</p>
                </div>

                {/* Max parallel */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-white/40 text-xs">Max Parallel: {maxParallel}</label>
                    {parsedNumbers.length > 1 && maxParallel < parsedNumbers.length && (
                      <button
                        onClick={() => setMaxParallel(parsedNumbers.length)}
                        className="text-white/30 hover:text-white text-xs transition-colors"
                      >
                        All ({parsedNumbers.length})
                      </button>
                    )}
                  </div>
                  <input
                    type="range" min={1} max={Math.max(parsedNumbers.length, 1)}
                    value={Math.min(maxParallel, Math.max(parsedNumbers.length, 1))}
                    onChange={e => setMaxParallel(Number(e.target.value))}
                    className="w-full accent-white"
                  />
                  <div className="flex justify-between text-white/20 text-xs">
                    <span>1</span>
                    <span>{Math.max(parsedNumbers.length, 1)}</span>
                  </div>
                  {maxParallel === 1 ? (
                    <p className="text-white/30 text-xs">
                      One browser, runs sequentially
                    </p>
                  ) : (
                    <p className="text-white/30 text-xs">
                      {maxParallel} browsers, each starting 10s apart
                    </p>
                  )}
                </div>

                {/* Start */}
                <button
                  onClick={handleStart}
                  disabled={running || parsedNumbers.length === 0 || !selectedFlow}
                  className="w-full flex items-center justify-center gap-2 bg-white text-black font-medium text-sm py-2.5 rounded-lg hover:bg-white/90 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  {running
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> Running...</>
                    : <><Play className="w-4 h-4" /> Start Bulk Run</>
                  }
                </button>
              </div>

              {/* Bulk Environment */}
              <div className="bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden">
                <button
                  onClick={() => setEnvOpen(o => !o)}
                  className="w-full flex items-center justify-between px-5 py-3 hover:bg-white/[0.02] transition-colors"
                >
                  <span className="text-white text-sm font-semibold flex items-center gap-2">
                    <Settings2 className="w-4 h-4 text-white/40" /> Bulk Environment
                  </span>
                  {envOpen
                    ? <ChevronUp className="w-4 h-4 text-white/30" />
                    : <ChevronDown className="w-4 h-4 text-white/30" />
                  }
                </button>

                {envOpen && (
                  <div className="px-4 pb-4 space-y-2 border-t border-white/5">
                    <p className="text-white/20 text-xs pt-3">
                      Shared vars for all runs — COS_URL, PORTAL_URL, TOPUP_AMOUNT …
                    </p>
                    <div className="space-y-1.5 max-h-60 overflow-y-auto pr-1">
                      {envRows.map((row, i) => (
                        <div key={i} className="flex gap-1.5 items-center">
                          <input
                            value={row.key}
                            onChange={e => updateEnvRow(i, "key", e.target.value)}
                            placeholder="KEY"
                            className="w-2/5 bg-white/5 border border-white/10 rounded px-2 py-1.5 text-white text-xs font-mono focus:outline-none focus:border-white/30 placeholder:text-white/20"
                          />
                          <input
                            value={row.value}
                            onChange={e => updateEnvRow(i, "value", e.target.value)}
                            placeholder="value"
                            className="flex-1 bg-white/5 border border-white/10 rounded px-2 py-1.5 text-white text-xs font-mono focus:outline-none focus:border-white/30 placeholder:text-white/20"
                          />
                          <button onClick={() => removeEnvRow(i)} className="text-white/20 hover:text-red-400 transition-colors shrink-0">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2 pt-1">
                      <button onClick={addEnvRow} className="flex items-center gap-1 text-white/30 hover:text-white text-xs transition-colors">
                        <Plus className="w-3 h-3" /> Add variable
                      </button>
                      <div className="flex-1" />
                      <button
                        onClick={saveEnv}
                        disabled={envSaving}
                        className="flex items-center gap-1.5 bg-white/10 hover:bg-white/20 text-white text-xs px-3 py-1.5 rounded-lg transition-colors disabled:opacity-40"
                      >
                        {envSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : envSaved ? <CheckCircle2 className="w-3 h-3 text-green-400" /> : <Save className="w-3 h-3" />}
                        {envSaved ? "Saved" : "Save"}
                      </button>
                    </div>
                  </div>
                )}
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

            {/* ── Results ── */}
            <div className="col-span-2">
              {!activeBulk ? (
                <div className="h-full flex items-center justify-center border border-white/5 rounded-xl">
                  <div className="text-center text-white/20">
                    <Layers className="w-10 h-10 mx-auto mb-3 opacity-30" />
                    <p className="text-sm">Enter numbers and start a bulk run</p>
                  </div>
                </div>
              ) : (
                <div className="bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden">

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

                  {activeBulk.status === "running" && (
                    <div className="h-0.5 bg-white/5">
                      <div className="h-full bg-white/60 transition-all duration-500" style={{ width: `${progress}%` }} />
                    </div>
                  )}

                  {activeBulk.status === "completed" && activeBulk.success === activeBulk.total && (
                    <div className="flex items-center gap-3 mx-5 my-3 px-4 py-3 bg-white/[0.04] border border-white/20 rounded-lg">
                      <CheckCircle2 className="w-5 h-5 text-white shrink-0" />
                      <div>
                        <div className="text-white text-sm font-semibold">Flow Success</div>
                        <div className="text-white/40 text-xs">All {activeBulk.total} runs completed successfully</div>
                      </div>
                    </div>
                  )}
                  {activeBulk.status === "completed" && activeBulk.failed > 0 && (
                    <div className="flex items-center gap-3 mx-5 my-3 px-4 py-3 bg-white/[0.02] border border-white/10 rounded-lg">
                      <XCircle className="w-5 h-5 text-white/40 shrink-0" />
                      <div>
                        <div className="text-white/60 text-sm font-semibold">Flow Completed with Failures</div>
                        <div className="text-white/30 text-xs">{activeBulk.success} succeeded · {activeBulk.failed} failed</div>
                      </div>
                    </div>
                  )}

                  <div className="grid grid-cols-[1fr_90px_100px_1fr_60px] gap-4 px-5 py-2 border-b border-white/5 text-white/20 text-xs">
                    <span>Number</span><span>Duration</span><span>Status</span><span>Error</span><span></span>
                  </div>

                  <div className="divide-y divide-white/5 max-h-[520px] overflow-y-auto">
                    {activeBulk.items.map((item, i) => (
                      <div key={i} className="grid grid-cols-[1fr_90px_100px_1fr_60px] gap-4 items-center px-5 py-3 hover:bg-white/[0.02]">
                        <div className="flex items-center gap-2.5 min-w-0">
                          {statusIcon(item.status)}
                          <span className={`text-sm font-mono ${statusText(item.status)}`}>{item.number}</span>
                        </div>
                        <span className="text-white/30 text-xs">
                          {item.duration_seconds != null ? formatDuration(item.duration_seconds) : "—"}
                        </span>
                        <span className={`text-xs font-medium ${
                          item.status === "success" ? "text-white" :
                          item.status === "failed"  ? "text-white/40" :
                          item.status === "running" ? "text-white/60" :
                          "text-white/20"
                        }`}>
                          {item.status === "success" ? "Success" :
                           item.status === "failed"  ? "Failed"  :
                           item.status === "running" ? "Running" :
                           "Pending"}
                        </span>
                        <span className="text-red-400/50 text-xs truncate" title={item.error ?? ""}>{item.error ?? ""}</span>
                        <div className="flex justify-end">
                          {item.execution_id && (
                            <Link href={`/execution/${item.execution_id}`} className="flex items-center gap-1 text-white/30 hover:text-white text-xs transition-colors">
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

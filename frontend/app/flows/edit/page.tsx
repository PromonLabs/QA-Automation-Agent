"use client"

import { Suspense, useEffect, useState, useCallback } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { diskFlowsApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { Loader2, Save, Play, ArrowLeft, CheckCircle2, AlertCircle } from "lucide-react"
import { cn } from "@/lib/utils"

export default function FlowEditPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen bg-black items-center justify-center text-white/20">
        <Loader2 className="animate-spin" />
      </div>
    }>
      <FlowEditInner />
    </Suspense>
  )
}

function FlowEditInner() {
  const router = useRouter()
  const params = useSearchParams()
  const flowId = params.get("id") ?? ""

  const [content, setContent] = useState("")
  const [original, setOriginal] = useState("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState("")

  const flowName = flowId.split("/").pop()?.replace(/-/g, " ") ?? flowId
  const isJson = flowId.startsWith("json-flow/")
  const isDirty = content !== original

  useEffect(() => {
    if (!flowId) return
    setLoading(true)
    diskFlowsApi.getContent(flowId)
      .then(r => {
        setContent(r.data.content)
        setOriginal(r.data.content)
      })
      .catch(() => setError("Failed to load flow file."))
      .finally(() => setLoading(false))
  }, [flowId])

  const save = useCallback(async () => {
    setSaving(true)
    setError("")
    try {
      await diskFlowsApi.saveContent(flowId, content)
      setOriginal(content)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to save.")
    } finally {
      setSaving(false)
    }
  }, [flowId, content])

  const saveAndRun = useCallback(async () => {
    setRunning(true)
    setError("")
    try {
      await diskFlowsApi.saveContent(flowId, content)
      setOriginal(content)
      const { data } = await diskFlowsApi.run(flowId)
      router.push(`/execution/${data.id}`)
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to save or run.")
      setRunning(false)
    }
  }, [flowId, content, router])

  // Ctrl+S to save
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault()
        save()
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [save])

  // Count steps
  const stepCount = (() => {
    if (!content.trim()) return 0
    try {
      const parsed = JSON.parse(content)
      const steps = parsed.steps ?? parsed?.task?.steps ?? []
      return Array.isArray(steps) ? steps.filter((s: unknown) => typeof s === "string" && (s as string).trim().length > 3).length : 0
    } catch {
      return content.split("\n").filter(l => l.trim().length > 3).length
    }
  })()

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Edit Flow" />
        <main className="flex-1 flex flex-col p-6 gap-4">

          {/* Top bar */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={() => router.push("/flows")}
                className="flex items-center gap-1.5 text-white/30 hover:text-white text-sm transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
                Flows
              </button>
              <span className="text-white/10">/</span>
              <span className="text-white font-medium text-sm">{flowName}</span>
              <span className={cn(
                "text-xs border rounded px-1.5 py-0.5",
                isJson ? "border-blue-500/20 text-blue-400/60" : "border-green-500/20 text-green-400/60"
              )}>
                {isJson ? "JSON" : "Normal"}
              </span>
              {isDirty && (
                <span className="text-white/30 text-xs border border-white/10 rounded px-1.5 py-0.5">
                  unsaved
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <span className="text-white/20 text-xs">
                {stepCount} step{stepCount !== 1 ? "s" : ""}
              </span>
              <span className="text-white/10 text-xs">Ctrl+S to save</span>

              <button
                onClick={save}
                disabled={saving || running || !isDirty}
                className="flex items-center gap-1.5 border border-white/20 text-white px-4 py-2
                           rounded-lg text-sm hover:bg-white/5 transition-colors disabled:opacity-40"
              >
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> :
                 saved   ? <CheckCircle2 className="w-3.5 h-3.5 text-green-400" /> :
                           <Save className="w-3.5 h-3.5" />}
                {saved ? "Saved" : "Save"}
              </button>

              <button
                onClick={saveAndRun}
                disabled={saving || running}
                className="flex items-center gap-1.5 bg-white text-black font-semibold px-4 py-2
                           rounded-lg text-sm hover:bg-white/90 transition-colors disabled:opacity-40"
              >
                {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                Save &amp; Run
              </button>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-center gap-2 px-4 py-3 bg-red-500/10 border border-red-500/20
                            rounded-lg text-red-400 text-sm">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          {/* Editor */}
          {loading ? (
            <div className="flex-1 flex items-center justify-center text-white/20">
              <Loader2 className="w-6 h-6 animate-spin" />
            </div>
          ) : (
            <div className="flex-1 flex flex-col min-h-0">
              <textarea
                value={content}
                onChange={e => setContent(e.target.value)}
                spellCheck={false}
                className="flex-1 w-full bg-white/[0.03] border border-white/10 rounded-xl
                           px-5 py-4 text-white text-sm font-mono resize-none
                           focus:outline-none focus:border-white/30 transition-colors
                           leading-relaxed"
                style={{ minHeight: "calc(100vh - 260px)" }}
              />
            </div>
          )}

        </main>
      </div>
    </div>
  )
}

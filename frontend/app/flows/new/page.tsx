"use client"

import { useState, useRef, useCallback } from "react"
import { useRouter } from "next/navigation"
import { diskFlowsApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { Loader2, Upload, Save, X, FileText } from "lucide-react"
import { cn } from "@/lib/utils"

export default function NewFlowPage() {
  const router = useRouter()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [name, setName]             = useState("")
  const [task, setTask]             = useState("")
  const [format, setFormat]         = useState<"natural" | "json">("json")
  const [saving, setSaving]         = useState(false)
  const [error, setError]           = useState("")
  const [uploadedFile, setUploadedFile] = useState<string | null>(null)
  const [dragOver, setDragOver]     = useState(false)

  // ── File upload ──────────────────────────────────────────────────────────────
  const handleFile = useCallback(async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".json")) {
      setError("Only .json files are supported")
      return
    }
    setError("")
    try {
      const text = await file.text()
      const raw  = JSON.parse(text)
      // Extract steps from any common JSON shape
      let steps: string[] = []
      if (Array.isArray(raw)) {
        steps = raw.map(String)
      } else if (Array.isArray(raw.steps)) {
        steps = raw.steps.map(String)
      } else if (Array.isArray(raw?.task?.steps)) {
        steps = raw.task.steps.map(String)
      }
      const stem = file.name.replace(/\.json$/i, "").replace(/[-_]/g, " ")
      setName(raw.name?.trim() || stem)
      setTask(JSON.stringify({ name: raw.name?.trim() || stem, steps }, null, 2))
      setFormat("json")
      setUploadedFile(file.name)
    } catch {
      setError("Could not parse JSON — check that the file is valid.")
    }
  }, [])

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) handleFile(f)
    e.target.value = ""
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  const clearUpload = () => {
    setUploadedFile(null); setTask(""); setName("")
  }

  // ── Save ─────────────────────────────────────────────────────────────────────
  const save = async () => {
    if (!task.trim()) { setError("Please write or upload flow steps."); return }
    setSaving(true); setError("")
    try {
      await diskFlowsApi.create(
        name.trim() || "Untitled Flow",
        task.trim(),
        format,
      )
      router.push("/flows")
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to save")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Write Flow" />
        <main className="flex-1 p-8 max-w-2xl space-y-5">

          {/* Flow Name */}
          <div>
            <label className="text-white/40 text-xs uppercase tracking-widest mb-2 block">
              Flow Name
            </label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="My QA Flow"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-white
                         text-sm placeholder-white/20 focus:outline-none focus:border-white/30
                         transition-colors"
            />
          </div>

          {/* Upload zone */}
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            className={cn(
              "border-2 border-dashed rounded-xl px-6 py-5 text-center cursor-pointer transition-all",
              dragOver
                ? "border-white/50 bg-white/10"
                : "border-white/10 hover:border-white/25 hover:bg-white/[0.02]"
            )}
          >
            <input ref={fileInputRef} type="file" accept=".json" className="hidden" onChange={onFileInput} />
            {uploadedFile ? (
              <div className="flex items-center justify-center gap-3">
                <div className="flex items-center gap-2 bg-white/10 border border-white/20 rounded-lg px-4 py-2">
                  <FileText className="w-4 h-4 text-white/60" />
                  <span className="text-white text-sm">{uploadedFile}</span>
                  <button
                    onClick={e => { e.stopPropagation(); clearUpload() }}
                    className="ml-1 text-white/30 hover:text-white/70 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
                <span className="text-white/25 text-xs">Click to replace</span>
              </div>
            ) : (
              <div className="flex items-center justify-center gap-2 text-white/30 hover:text-white/50 transition-colors">
                <Upload className="w-4 h-4" />
                <span className="text-sm">Upload a JSON flow file or drag &amp; drop</span>
              </div>
            )}
          </div>

          {/* Steps editor */}
          <div>
            <label className="text-white/40 text-xs uppercase tracking-widest mb-2 block">
              Steps
            </label>
            <textarea
              value={task}
              onChange={e => setTask(e.target.value)}
              rows={18}
              spellCheck={false}
              placeholder={'{\n  "name": "My Flow",\n  "steps": [\n    "Navigate to ${URL}",\n    "Click the Login button",\n    "..."\n  ]\n}'}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-white
                         text-sm font-mono placeholder-white/15 focus:outline-none focus:border-white/30
                         transition-colors resize-none"
            />
          </div>

          {/* Error */}
          {error && (
            <p className="text-red-400/80 text-sm">{error}</p>
          )}

          {/* Save */}
          <button
            onClick={save}
            disabled={saving}
            className="flex items-center gap-2 bg-white text-black font-semibold px-6 py-2.5
                       rounded-lg text-sm hover:bg-white/90 transition-colors disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save Flow
          </button>

        </main>
      </div>
    </div>
  )
}

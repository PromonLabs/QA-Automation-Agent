"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { diskFlowsApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { DiskFlow } from "@/types"
import {
  Play, Loader2, FileText, Code2, FolderOpen, Folder, ArrowLeft, ExternalLink, CheckCircle2, Pencil, Trash2
} from "lucide-react"
import { cn } from "@/lib/utils"

// Flows are grouped into folders by name. Anything that doesn't match a
// known group falls into "Other Flows" so nothing gets lost as new flows are added.
type FolderDef = { key: string; name: string; match: (f: DiskFlow) => boolean }

const FOLDER_DEFS: FolderDef[] = [
  {
    key: "mobile",
    name: "Mobile Flows",
    match: (f) => [
      "mobile data add",
      "new account creation",
      "tusass extra data add",
      "tusass topup talk",
    ].includes(f.name.trim().toLowerCase()),
  },
  {
    key: "internet",
    name: "Internet Flows",
    match: (f) => f.name.trim().toLowerCase().includes("internet"),
  },
]

function groupFlowsByFolder(flows: DiskFlow[]) {
  const used = new Set<string>()
  const groups = FOLDER_DEFS.map(def => {
    const items = flows.filter(f => !used.has(f.id) && def.match(f))
    items.forEach(f => used.add(f.id))
    return { ...def, items }
  })
  const other = flows.filter(f => !used.has(f.id))
  if (other.length > 0) {
    groups.push({ key: "other", name: "Other Flows", match: () => false, items: other })
  }
  return groups.filter(g => g.items.length > 0)
}

export default function FlowsPage() {
  const router = useRouter()
  const [flows, setFlows]   = useState<DiskFlow[]>([])
  const [loading, setLoading] = useState(true)
  // Track multiple running flows: flowId → executionId (once started)
  const [running, setRunning] = useState<Record<string, string | true>>({})
  const [error, setError]   = useState("")
  const [openFolder, setOpenFolder] = useState<string | null>(null)

  useEffect(() => {
    diskFlowsApi.list()
      .then(r => setFlows(r.data))
      .catch(() => setError("Failed to load flows from disk"))
      .finally(() => setLoading(false))
  }, [])

  const deleteFlow = async (flow: DiskFlow) => {
    if (!confirm(`Delete "${flow.name}"? This cannot be undone.`)) return
    try {
      await diskFlowsApi.delete(flow.id)
      setFlows(prev => prev.filter(f => f.id !== flow.id))
    } catch {
      setError("Failed to delete flow.")
    }
  }

  const runFlow = async (flow: DiskFlow) => {
    setRunning(prev => ({ ...prev, [flow.id]: true }))
    setError("")
    try {
      const { data } = await diskFlowsApi.run(flow.id)
      // Open execution in a new tab — stay on this page so more flows can be started
      window.open(`/execution/${data.id}`, "_blank", "noopener,noreferrer")
      setRunning(prev => ({ ...prev, [flow.id]: data.id }))
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to start execution")
      setRunning(prev => {
        const next = { ...prev }
        delete next[flow.id]
        return next
      })
    }
  }

  const folders = groupFlowsByFolder(flows)
  const activeFolder = folders.find(f => f.key === openFolder) || null

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Flows" />
        <main className="flex-1 p-8">

          {error && (
            <div className="mb-4 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex justify-center py-20 text-white/20">
              <Loader2 className="animate-spin" />
            </div>
          ) : flows.length === 0 ? (
            <div className="text-center py-20">
              <FolderOpen className="w-10 h-10 text-white/10 mx-auto mb-3" />
              <div className="text-white/20 text-sm">
                No flows found in the <code className="text-white/30">flows/</code> folder
              </div>
            </div>
          ) : activeFolder ? (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <button
                  onClick={() => setOpenFolder(null)}
                  className="flex items-center gap-1 text-white/40 hover:text-white text-xs
                             border border-white/10 hover:border-white/30 rounded-md px-2 py-1 mr-2 transition-colors"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  Back
                </button>
                <FolderOpen className="w-4 h-4 text-white/40" />
                <h2 className="text-white/60 text-sm font-medium uppercase tracking-widest">
                  {activeFolder.name}
                </h2>
                <span className="text-white/20 text-xs border border-white/10 rounded px-1.5 py-0.5">
                  {activeFolder.items.length}
                </span>
              </div>
              <div className="grid gap-3">
                {activeFolder.items.map(flow => (
                  <FlowCard
                    key={flow.id}
                    flow={flow}
                    runState={running[flow.id]}
                    onRun={() => runFlow(flow)}
                    onView={(execId) => window.open(`/execution/${execId}`, "_blank", "noopener,noreferrer")}
                    onEdit={() => router.push(`/flows/edit?id=${encodeURIComponent(flow.id)}`)}
                    onDelete={() => deleteFlow(flow)}
                  />
                ))}
              </div>
            </section>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {folders.map(folder => (
                <FolderCard
                  key={folder.key}
                  name={folder.name}
                  items={folder.items}
                  onOpen={() => setOpenFolder(folder.key)}
                />
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

function FolderCard({
  name,
  items,
  onOpen,
}: {
  name: string
  items: DiskFlow[]
  onOpen: () => void
}) {
  const preview = items.slice(0, 3).map(f => f.name).join(", ")
  const extra = items.length > 3 ? ` +${items.length - 3} more` : ""

  return (
    <button
      onClick={onOpen}
      className="text-left bg-white/[0.03] border border-white/10 rounded-xl px-5 py-4
                 hover:border-white/20 hover:bg-white/[0.05] transition-colors group"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <Folder className="w-4 h-4 text-white/40 shrink-0 group-hover:text-white/70 transition-colors" />
          <span className="text-white font-medium text-sm truncate">{name}</span>
        </div>
        <span className="text-white/20 text-xs border border-white/10 rounded px-1.5 py-0.5 shrink-0">
          {items.length}
        </span>
      </div>
      <div className="text-white/20 text-xs mt-2 ml-6 truncate">
        {preview}{extra}
      </div>
    </button>
  )
}

function FlowCard({
  flow,
  runState,
  onRun,
  onView,
  onEdit,
  onDelete,
}: {
  flow: DiskFlow
  runState: string | true | undefined
  onRun: () => void
  onView: (execId: string) => void
  onEdit: () => void
  onDelete: () => void
}) {
  const isJson = flow.flow_type === "json"
  const isStarting = runState === true
  const execId = typeof runState === "string" ? runState : null

  return (
    <div className="flex items-center justify-between bg-white/[0.03] border border-white/10
                    rounded-xl px-5 py-4 hover:border-white/20 transition-colors group">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {isJson
            ? <Code2 className="w-4 h-4 text-white/30 shrink-0" />
            : <FileText className="w-4 h-4 text-white/30 shrink-0" />}
          <span className="text-white font-medium text-sm">{flow.name}</span>
          <span className={cn(
            "text-xs border rounded px-1.5 py-0.5",
            isJson
              ? "border-blue-500/20 text-blue-400/60"
              : "border-green-500/20 text-green-400/60"
          )}>
            {isJson ? "JSON" : "Normal"}
          </span>
        </div>
        <div className="text-white/20 text-xs mt-2 ml-6 font-mono truncate max-w-2xl">
          {flow.preview.slice(0, 120)}{flow.preview.length > 120 ? "…" : ""}
        </div>
      </div>

      <div className="flex items-center gap-2 ml-4 shrink-0">
        <span className="text-white/20 text-xs font-mono">{flow.filename}</span>

        {/* Edit button */}
        <button
          onClick={onEdit}
          className="flex items-center gap-1 text-white/30 hover:text-white border border-white/10
                     hover:border-white/30 text-xs px-2.5 py-1.5 rounded-md transition-colors"
        >
          <Pencil className="w-3 h-3" />
          Edit
        </button>

        {/* Delete button */}
        <button
          onClick={onDelete}
          className="flex items-center gap-1 text-white/20 hover:text-red-400 border border-white/10
                     hover:border-red-500/30 text-xs px-2.5 py-1.5 rounded-md transition-colors"
        >
          <Trash2 className="w-3 h-3" />
        </button>

        {execId ? (
          // Started — show green "Running" badge + View button
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 text-green-400 text-xs font-medium">
              <CheckCircle2 className="w-3 h-3" />
              Started
            </span>
            <button
              onClick={() => onView(execId)}
              className="flex items-center gap-1.5 bg-green-500/10 border border-green-500/20
                         text-green-400 text-xs font-medium px-3 py-1.5 rounded-md
                         hover:bg-green-500/20 transition-colors"
            >
              <ExternalLink className="w-3 h-3" />
              View
            </button>
          </div>
        ) : (
          <button
            onClick={onRun}
            disabled={isStarting}
            className="flex items-center gap-1.5 bg-white text-black text-xs font-medium
                       px-3 py-1.5 rounded-md hover:bg-white/90 transition-colors disabled:opacity-50"
          >
            {isStarting
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : <Play className="w-3 h-3" />}
            Run
          </button>
        )}
      </div>
    </div>
  )
}

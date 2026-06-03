"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { executionApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { Execution } from "@/types"
import { formatDate, formatDuration, statusColor } from "@/lib/utils"
import { Loader2, Activity, CheckCircle2, XCircle, Clock, Ban } from "lucide-react"
import { cn } from "@/lib/utils"

const statusIcon = (s: string) => {
  switch (s) {
    case "success": return <CheckCircle2 className="w-3.5 h-3.5" />
    case "failed": return <XCircle className="w-3.5 h-3.5" />
    case "running": return <Activity className="w-3.5 h-3.5 animate-pulse" />
    case "cancelled": return <Ban className="w-3.5 h-3.5" />
    default: return <Clock className="w-3.5 h-3.5" />
  }
}

export default function ExecutionsPage() {
  const router = useRouter()
  const [executions, setExecutions] = useState<Execution[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<string>("all")

  useEffect(() => {
    executionApi.list().then(r => setExecutions(r.data)).finally(() => setLoading(false))
  }, [router])

  const filtered = filter === "all" ? executions : executions.filter(e => e.status === filter)

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Executions" />
        <main className="flex-1 p-8">

          {/* Filter tabs */}
          <div className="flex items-center gap-2 mb-6">
            {["all", "running", "success", "failed", "cancelled"].map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn(
                  "px-3 py-1.5 rounded-md text-xs capitalize transition-all border",
                  filter === f
                    ? "bg-white text-black border-white font-medium"
                    : "text-white/40 border-white/10 hover:text-white hover:border-white/20"
                )}
              >
                {f}
              </button>
            ))}
            <span className="ml-auto text-white/20 text-xs">{filtered.length} result{filtered.length !== 1 ? "s" : ""}</span>
          </div>

          {loading ? (
            <div className="flex justify-center py-20"><Loader2 className="animate-spin text-white/20" /></div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-20 text-white/20 text-sm">No executions found</div>
          ) : (
            <div className="space-y-2">
              {filtered.map(exec => (
                <Link key={exec.id} href={`/execution/${exec.id}`}
                  className="flex items-center gap-4 bg-white/[0.03] border border-white/10 rounded-xl px-5 py-4 hover:border-white/25 hover:bg-white/[0.05] transition-all group">

                  <div className={cn("flex items-center gap-1.5 text-xs px-2.5 py-1 rounded border shrink-0", statusColor(exec.status))}>
                    {statusIcon(exec.status)}
                    {exec.status}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="text-white text-sm font-medium">{exec.flow_name}</div>
                    <div className="text-white/30 text-xs mt-0.5">{formatDate(exec.started_at)}</div>
                  </div>

                  <div className="text-right shrink-0 space-y-1">
                    <div className="text-white/50 text-xs">{formatDuration(exec.duration_seconds)}</div>
                    <div className="text-white/20 text-xs">
                      {exec.steps_completed}/{exec.steps_total} steps
                    </div>
                  </div>

                  {exec.result_summary && (
                    <div className="text-white/20 text-xs max-w-xs truncate hidden xl:block">
                      {exec.result_summary}
                    </div>
                  )}
                </Link>
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

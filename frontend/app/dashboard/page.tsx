"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { diskFlowsApi, executionApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { DiskFlow, Execution } from "@/types"
import { formatDate, formatDuration, statusColor } from "@/lib/utils"
import {
  Play, Activity, CheckCircle2, XCircle, Zap, ArrowRight, FileBadge
} from "lucide-react"

export default function Dashboard() {
  const router = useRouter()
  const [flows, setFlows] = useState<DiskFlow[]>([])
  const [executions, setExecutions] = useState<Execution[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([diskFlowsApi.list(), executionApi.list()])
      .then(([f, e]) => { setFlows(f.data); setExecutions(e.data) })
      .finally(() => setLoading(false))
  }, [router])

  const stats = {
    total: executions.length,
    success: executions.filter(e => e.status === "success").length,
    failed: executions.filter(e => e.status === "failed").length,
    flows: flows.length,
  }

  const recent = executions.slice(0, 5)

  if (loading) {
    return (
      <div className="flex min-h-screen bg-black">
        <Sidebar />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-white/30 text-sm animate-pulse">Loading…</div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Dashboard" />
        <main className="flex-1 p-8 space-y-8">

          {/* Stats */}
          <div className="grid grid-cols-4 gap-4">
            {[
              { label: "Total Runs", value: stats.total, icon: Activity, sub: "all time" },
              { label: "Successful", value: stats.success, icon: CheckCircle2, sub: "completed" },
              { label: "Failed", value: stats.failed, icon: XCircle, sub: "need attention" },
              { label: "Available Flows", value: stats.flows, icon: Zap, sub: "on disk" },
            ].map(({ label, value, icon: Icon, sub }) => (
              <div key={label} className="bg-white/[0.03] border border-white/10 rounded-xl p-5">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-white/40 text-xs uppercase tracking-widest">{label}</div>
                    <div className="text-white text-3xl font-bold mt-2">{value}</div>
                    <div className="text-white/20 text-xs mt-1">{sub}</div>
                  </div>
                  <Icon className="w-5 h-5 text-white/20" />
                </div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Recent executions */}
            <div className="bg-white/[0.03] border border-white/10 rounded-xl">
              <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
                <h2 className="text-white text-sm font-semibold">Recent Executions</h2>
                <Link href="/execution" className="text-white/30 hover:text-white text-xs flex items-center gap-1">
                  View all <ArrowRight className="w-3 h-3" />
                </Link>
              </div>
              <div className="divide-y divide-white/5">
                {recent.length === 0 && (
                  <div className="px-5 py-8 text-center text-white/20 text-sm">No executions yet</div>
                )}
                {recent.map(exec => (
                  <Link key={exec.id} href={`/execution/${exec.id}`}
                    className="flex items-center justify-between px-5 py-3.5 hover:bg-white/5 transition-colors">
                    <div className="min-w-0">
                      <div className="text-white text-sm font-medium truncate">{exec.flow_name}</div>
                      <div className="text-white/30 text-xs mt-0.5">{formatDate(exec.started_at)}</div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0 ml-3">
                      <span className="text-white/30 text-xs">{formatDuration(exec.duration_seconds)}</span>
                      <span className={`text-xs px-2 py-0.5 rounded border ${statusColor(exec.status)}`}>
                        {exec.status}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            </div>

            {/* Available Flows */}
            <div className="bg-white/[0.03] border border-white/10 rounded-xl">
              <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
                <h2 className="text-white text-sm font-semibold">Available Flows</h2>
                <Link href="/flows" className="text-white/30 hover:text-white text-xs flex items-center gap-1">
                  View all <ArrowRight className="w-3 h-3" />
                </Link>
              </div>
              <div className="divide-y divide-white/5">
                {flows.length === 0 && (
                  <div className="px-5 py-8 text-center text-white/20 text-sm">
                    No flows found in <code className="text-white/30">flows/</code> folder
                  </div>
                )}
                {flows.slice(0, 5).map(flow => (
                  <div key={flow.id} className="flex items-center justify-between px-5 py-3.5">
                    <div className="min-w-0">
                      <div className="text-white text-sm font-medium truncate">{flow.name}</div>
                      <div className="text-white/30 text-xs mt-0.5 capitalize">{flow.flow_type} flow</div>
                    </div>
                    <Link href="/flows"
                      className="shrink-0 ml-3 flex items-center gap-1.5 bg-white text-black text-xs font-medium px-3 py-1.5 rounded-md hover:bg-white/90 transition-colors">
                      <Play className="w-3 h-3" /> Run
                    </Link>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Reports quick link */}
          {executions.filter(e => e.status === "success").length > 0 && (
            <div className="bg-white/[0.03] border border-white/10 rounded-xl px-5 py-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <FileBadge className="w-5 h-5 text-white/30" />
                <div>
                  <div className="text-white text-sm font-medium">Reports Available</div>
                  <div className="text-white/30 text-xs">
                    {executions.filter(e => e.status === "success").length} completed execution{executions.filter(e => e.status === "success").length !== 1 ? "s" : ""} with reports
                  </div>
                </div>
              </div>
              <Link href="/reports"
                className="flex items-center gap-1.5 border border-white/20 text-white/60 hover:text-white px-4 py-2 rounded-lg text-sm transition-colors">
                View Reports <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          )}

        </main>
      </div>
    </div>
  )
}

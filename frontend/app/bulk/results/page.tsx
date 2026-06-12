"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { bulkApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { BulkRun } from "@/types"
import { formatDuration } from "@/lib/utils"
import {
  CheckCircle2, XCircle, Loader2, Clock,
  BarChart2, ChevronRight, Layers,
} from "lucide-react"

export default function BulkResultsListPage() {
  const [history, setHistory] = useState<BulkRun[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    bulkApi.list()
      .then(r => setHistory(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Bulk Results" />
        <main className="flex-1 p-8">
          <div className="max-w-4xl mx-auto space-y-6">

            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-white font-semibold text-lg">Bulk Run History</h1>
                <p className="text-white/30 text-xs mt-0.5">Click a run to view screenshots and details</p>
              </div>
              <Link
                href="/bulk"
                className="flex items-center gap-2 text-xs px-4 py-2 rounded-lg bg-white text-black font-medium hover:bg-white/90 transition-colors"
              >
                <Layers className="w-3.5 h-3.5" /> New Bulk Run
              </Link>
            </div>

            {loading ? (
              <div className="flex items-center justify-center h-48 text-white/30">
                <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading…
              </div>
            ) : history.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-64 border border-white/5 rounded-xl gap-3">
                <BarChart2 className="w-10 h-10 text-white/10" />
                <p className="text-white/20 text-sm">No bulk runs yet</p>
                <Link href="/bulk" className="text-white/40 hover:text-white text-xs underline transition-colors">
                  Start your first bulk run
                </Link>
              </div>
            ) : (
              <div className="space-y-3">
                {history.map(run => {
                  const allPassed = run.failed === 0 && run.status === "completed"
                  const hasFailed = run.failed > 0
                  const isRunning = run.status === "running"

                  return (
                    <Link
                      key={run.id}
                      href={`/bulk/${run.id}`}
                      className="group flex items-center gap-5 bg-white/[0.03] hover:bg-white/[0.05] border border-white/10 hover:border-white/20 rounded-xl px-5 py-4 transition-all"
                    >
                      {/* Status icon */}
                      <div className="shrink-0">
                        {isRunning  && <Loader2 className="w-5 h-5 text-white/40 animate-spin" />}
                        {allPassed  && <CheckCircle2 className="w-5 h-5 text-green-400" />}
                        {hasFailed  && <XCircle className="w-5 h-5 text-red-400/70" />}
                        {!isRunning && !allPassed && !hasFailed && (
                          <Clock className="w-5 h-5 text-white/20" />
                        )}
                      </div>

                      {/* Flow name + meta */}
                      <div className="flex-1 min-w-0">
                        <div className="text-white text-sm font-medium truncate">{run.flow_name}</div>
                        <div className="text-white/30 text-xs mt-0.5 flex items-center gap-3">
                          <span>{run.total} items</span>
                          <span>·</span>
                          <span className="text-green-400/70">{run.success} passed</span>
                          {run.failed > 0 && (
                            <>
                              <span>·</span>
                              <span className="text-red-400/60">{run.failed} failed</span>
                            </>
                          )}
                        </div>
                      </div>

                      {/* Stats pills */}
                      <div className="shrink-0 flex items-center gap-4">
                        {/* Pass rate bar */}
                        <div className="hidden sm:flex flex-col items-end gap-1">
                          <div className="w-24 h-1.5 bg-white/5 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${allPassed ? "bg-green-400/60" : hasFailed ? "bg-orange-400/60" : "bg-white/30"}`}
                              style={{ width: `${run.total > 0 ? Math.round((run.success / run.total) * 100) : 0}%` }}
                            />
                          </div>
                          <span className="text-white/20 text-[10px]">
                            {run.total > 0 ? Math.round((run.success / run.total) * 100) : 0}% pass
                          </span>
                        </div>

                        {/* Date */}
                        <div className="text-white/30 text-xs text-right hidden md:block">
                          <div>{new Date(run.started_at).toLocaleDateString()}</div>
                          <div>{new Date(run.started_at).toLocaleTimeString()}</div>
                        </div>

                        {/* Status badge */}
                        <span className={`text-[11px] px-2.5 py-1 rounded-full border font-medium ${
                          isRunning
                            ? "text-white/50 border-white/20 bg-white/5"
                            : allPassed
                              ? "text-green-400 border-green-400/30 bg-green-400/10"
                              : "text-orange-400 border-orange-400/30 bg-orange-400/10"
                        }`}>
                          {isRunning ? "Running" : allPassed ? "All Passed" : `${run.failed} Failed`}
                        </span>

                        <ChevronRight className="w-4 h-4 text-white/20 group-hover:text-white/60 transition-colors" />
                      </div>
                    </Link>
                  )
                })}
              </div>
            )}

          </div>
        </main>
      </div>
    </div>
  )
}

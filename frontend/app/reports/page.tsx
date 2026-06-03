"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { executionApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { Report } from "@/types"
import { formatDate } from "@/lib/utils"
import {
  Loader2, FileDown, FileBadge, X, ArrowUpRight,
  Maximize2, Trash2, CheckCircle2, XCircle
} from "lucide-react"
import { cn } from "@/lib/utils"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
function pdfUrl(execId: string) { return `${API_URL}/api/execution/report/${execId}` }

function formatTime(iso: string | null) {
  if (!iso) return "—"
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" })
    + " · " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
}

interface CardProps {
  report: Report
  onView: (r: Report) => void
  onDelete: (r: Report) => void
  deleting: boolean
}

function ReportCard({ report, onView, onDelete, deleting }: CardProps) {
  const isSuccess = report.status === "success"
  return (
    <div className="group relative flex flex-col bg-white/[0.03] border border-white/10
                    rounded-xl overflow-hidden hover:border-white/20 transition-all">
      {/* Delete button */}
      <button
        onClick={e => { e.stopPropagation(); onDelete(report) }}
        disabled={deleting}
        className="absolute top-2 right-2 z-10 flex items-center justify-center w-7 h-7
                   rounded-md text-white/20 hover:text-red-400 hover:bg-red-500/10
                   opacity-0 group-hover:opacity-100 transition-all disabled:opacity-50"
      >
        {deleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
      </button>

      {/* Click area → open PDF */}
      <button onClick={() => onView(report)} className="flex flex-col flex-1 text-left">
        {/* Top: name */}
        <div className={cn(
          "flex items-center justify-center w-full px-4 py-6 border-b border-white/10 min-h-[90px]",
          isSuccess ? "bg-green-500/5" : "bg-red-500/5"
        )}>
          <span className="text-white font-semibold text-sm text-center leading-snug line-clamp-2">
            {report.flow_name}
          </span>
        </div>

        {/* Bottom: meta */}
        <div className="flex flex-col gap-1 p-3">
          <div className={cn(
            "flex items-center gap-1.5 text-xs font-medium",
            isSuccess ? "text-green-400" : "text-red-400"
          )}>
            {isSuccess
              ? <CheckCircle2 className="w-3.5 h-3.5" />
              : <XCircle className="w-3.5 h-3.5" />}
            {report.status}
          </div>
          <span className="text-white/25 text-xs font-mono">
            {formatTime(report.started_at)}
          </span>
        </div>
      </button>
    </div>
  )
}

export default function ReportsPage() {
  const [reports, setReports]     = useState<Report[]>([])
  const [loading, setLoading]     = useState(true)
  const [viewing, setViewing]     = useState<Report | null>(null)
  const [deleting, setDeleting]   = useState<string | null>(null)

  useEffect(() => {
    executionApi.listReports()
      .then(r => setReports(r.data))
      .finally(() => setLoading(false))
  }, [])

  const handleDelete = async (report: Report) => {
    setDeleting(report.exec_id)
    try {
      await executionApi.deleteReport(report.exec_id)
      setReports(prev => prev.filter(r => r.exec_id !== report.exec_id))
      if (viewing?.exec_id === report.exec_id) setViewing(null)
    } catch {}
    setDeleting(null)
  }

  const success = reports.filter(r => r.status === "success")
  const failed  = reports.filter(r => r.status !== "success")

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Reports" />
        <main className="flex-1 p-6">

          {loading ? (
            <div className="flex justify-center py-20 text-white/20">
              <Loader2 className="animate-spin" />
            </div>
          ) : reports.length === 0 ? (
            <div className="text-center py-20">
              <FileBadge className="w-10 h-10 text-white/10 mx-auto mb-3" />
              <div className="text-white/20 text-sm mb-4">No reports yet</div>
              <Link href="/flows"
                className="text-white/50 border border-white/20 px-4 py-2 rounded-lg text-sm hover:bg-white/5 transition-colors">
                Run a flow to generate a report
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-6 items-start">

              {/* ── Success column ── */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <CheckCircle2 className="w-4 h-4 text-green-400" />
                  <h2 className="text-white font-semibold text-sm">Success</h2>
                  <span className="text-white/30 text-xs ml-auto">{success.length}</span>
                </div>
                {success.length === 0 ? (
                  <div className="text-white/20 text-sm border border-dashed border-white/10 rounded-xl py-10 text-center">
                    No successful reports
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-3">
                    {success.map(r => (
                      <ReportCard
                        key={r.exec_id}
                        report={r}
                        onView={setViewing}
                        onDelete={handleDelete}
                        deleting={deleting === r.exec_id}
                      />
                    ))}
                  </div>
                )}
              </div>

              {/* ── Failed column ── */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <XCircle className="w-4 h-4 text-red-400" />
                  <h2 className="text-white font-semibold text-sm">Failed</h2>
                  <span className="text-white/30 text-xs ml-auto">{failed.length}</span>
                </div>
                {failed.length === 0 ? (
                  <div className="text-white/20 text-sm border border-dashed border-white/10 rounded-xl py-10 text-center">
                    No failed reports
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-3">
                    {failed.map(r => (
                      <ReportCard
                        key={r.exec_id}
                        report={r}
                        onView={setViewing}
                        onDelete={handleDelete}
                        deleting={deleting === r.exec_id}
                      />
                    ))}
                  </div>
                )}
              </div>

            </div>
          )}
        </main>
      </div>

      {/* ── PDF Viewer Modal ── */}
      {viewing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="relative w-[90vw] h-[92vh] bg-[#1a1a1a] border border-white/15 rounded-2xl
                          flex flex-col overflow-hidden shadow-2xl">

            <div className="flex items-center justify-between px-5 py-3 border-b border-white/10 shrink-0">
              <div className="flex items-center gap-3">
                <FileDown className="w-4 h-4 text-red-400/70" />
                <span className="text-white font-medium text-sm">{viewing.flow_name}</span>
                <span className={cn(
                  "flex items-center gap-1 text-xs px-2 py-0.5 rounded border",
                  viewing.status === "success"
                    ? "text-green-400 border-green-500/30 bg-green-500/10"
                    : "text-red-400 border-red-500/30 bg-red-500/10"
                )}>
                  {viewing.status === "success"
                    ? <CheckCircle2 className="w-3 h-3" />
                    : <XCircle className="w-3 h-3" />}
                  {viewing.status}
                </span>
                <span className="text-white/30 text-xs">{formatTime(viewing.started_at)}</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleDelete(viewing)}
                  disabled={deleting === viewing.exec_id}
                  className="flex items-center gap-1.5 text-red-400/60 hover:text-red-400 text-xs
                             border border-red-500/20 hover:border-red-500/40 px-3 py-1.5 rounded-md
                             transition-colors disabled:opacity-50"
                >
                  {deleting === viewing.exec_id
                    ? <Loader2 className="w-3 h-3 animate-spin" />
                    : <Trash2 className="w-3 h-3" />}
                  Delete
                </button>
                <Link href={`/execution/${viewing.exec_id}`} target="_blank"
                  className="flex items-center gap-1.5 text-white/30 hover:text-white text-xs
                             border border-white/10 hover:border-white/30 px-3 py-1.5 rounded-md transition-colors"
                  onClick={e => e.stopPropagation()}>
                  <ArrowUpRight className="w-3 h-3" /> Execution
                </Link>
                <a href={pdfUrl(viewing.exec_id)} target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-white/30 hover:text-white text-xs
                             border border-white/10 hover:border-white/30 px-3 py-1.5 rounded-md transition-colors">
                  <Maximize2 className="w-3 h-3" /> Full screen
                </a>
                <button onClick={() => setViewing(null)}
                  className="flex items-center justify-center w-8 h-8 text-white/40 hover:text-white
                             hover:bg-white/10 rounded-lg transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <iframe src={pdfUrl(viewing.exec_id)} className="flex-1 w-full border-0"
              title={`Report — ${viewing.flow_name}`} />
          </div>
        </div>
      )}
    </div>
  )
}

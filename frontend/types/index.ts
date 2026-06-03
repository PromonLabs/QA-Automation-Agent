export type ExecutionStatus = "pending" | "running" | "success" | "failed" | "cancelled"
export type FlowFormat = "natural" | "json"
export type LogLevel = "info" | "warning" | "error" | "success"

export interface Flow {
  id: string
  name: string
  description: string
  format: FlowFormat
  task: string
  tags: string[]
  env_vars: Record<string, string>
  created_at: string
  updated_at: string
}

export interface ExecutionLog {
  timestamp: string
  level: LogLevel
  message: string
  step: number | null
  screenshot: string | null
}

export interface Execution {
  id: string
  flow_id: string
  flow_name: string
  status: ExecutionStatus
  started_at: string
  finished_at: string | null
  duration_seconds: number | null
  logs: ExecutionLog[]
  screenshots: string[]
  result_summary: string | null
  error: string | null
  steps_completed: number
  steps_total: number
}

export interface DiskFlow {
  id: string
  name: string
  flow_type: "json" | "normal"
  filename: string
  preview: string
}

export interface Report {
  exec_id: string
  flow_name: string
  status: ExecutionStatus
  started_at: string | null
  filename: string
  ext: string
}

export interface WSMessage {
  type: "log" | "screenshot" | "status" | "complete" | "live_frame"
  data: Record<string, unknown>
}

import axios from "axios"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: { "Content-Type": "application/json" },
})


// ── Auth ──────────────────────────────────
export const authApi = {
  login: (username: string, password: string) =>
    api.post("/auth/login", { username, password }),
  me: () => api.get("/auth/me"),
}

// ── Flows ─────────────────────────────────
export const flowsApi = {
  list: () => api.get("/flows"),
  get: (id: string) => api.get(`/flows/${id}`),
  create: (data: {
    name: string
    description?: string
    format: "normal" | "json"
    task: string
    tags?: string[]
    env_vars?: Record<string, string>
  }) => api.post("/flows/create", data),
  delete: (id: string) => api.delete(`/flows/${id}`),

  /** Save per-flow environment variables / credentials */
  updateEnv: (id: string, env_vars: Record<string, string>) =>
    api.patch(`/flows/${id}/env`, { env_vars }),

  /** Upload a .json flow file — auto-parses name/steps/tags */
  upload: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return api.post("/flows/upload", form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
  },
}

// ── Disk Flows ────────────────────────────
export const diskFlowsApi = {
  list: () => api.get("/disk-flows"),
  create: (name: string, content: string, flowType: "json" | "normal" = "json") =>
    api.post("/disk-flows/create", { name, content, flow_type: flowType }),
  run: (flowId: string, headless?: boolean, envVars?: Record<string, string>) =>
    api.post("/disk-flows/run", { flow_id: flowId, headless, env_vars: envVars || {} }),
  getContent: (flowId: string) =>
    api.get<{ flow_id: string; content: string }>("/disk-flows/content", { params: { flow_id: flowId } }),
  saveContent: (flowId: string, content: string) =>
    api.put("/disk-flows/content", { flow_id: flowId, content }),
  delete: (flowId: string) =>
    api.delete("/disk-flows/delete", { params: { flow_id: flowId } }),
}

// ── Env vars (.env file) ──────────────────
export const envApi = {
  get: () => api.get<{ key: string; value: string }[]>("/disk-flows/env"),
  save: (vars: { key: string; value: string }[]) =>
    api.put("/disk-flows/env", { vars }),
}

// ── Executions ────────────────────────────
export const executionApi = {
  list: () => api.get("/execution"),
  get: (id: string) => api.get(`/execution/${id}`),
  start: (flowId: string, headless?: boolean) =>
    api.post("/execution", { flow_id: flowId, headless }),
  cancel: (id: string) => api.post(`/execution/${id}/cancel`),
  logs: (id: string) => api.get(`/execution/logs/${id}`),
  screenshots: (id: string) => api.get(`/execution/screenshots/${id}`),
  screenshotUrl: (execId: string, filename: string) =>
    `${API_URL}/api/execution/screenshot/${execId}/${filename}`,
  listReports: () => api.get("/execution/reports"),
  deleteReport: (execId: string) => api.delete(`/execution/report/${execId}`),
  reportUrl: (execId: string) => `${API_URL}/api/execution/report/${execId}`,
}

// ── Bulk ──────────────────────────────────
export const bulkApi = {
  run: (data: {
    flow_id: string
    numbers?: string[]
    subscribers?: { env_vars: Record<string, string>; label: string }[]
    variable_name?: string
    max_parallel: number
  }) => api.post("/bulk/run", data),
  list: () => api.get("/bulk"),
  get: (id: string) => api.get(`/bulk/${id}`),
  subscribers: () => api.get<import("@/types").Subscriber[]>("/bulk/subscribers"),
  getEnv: () => api.get<Record<string, string>>("/bulk/env"),
  saveEnv: (env_vars: Record<string, string>) => api.put("/bulk/env", { env_vars }),
}

// ── Chat (general-purpose gateway chatbot) ──
export const chatApi = {
  send: (
    messages: { role: "user" | "assistant"; content: string }[],
    provider?: "ollama" | "claude" | "gateway" | "gemini"
  ) =>
    api.post<{ reply: string; provider: string; model: string }>("/chat", { messages, provider }),
}

// ── Health ────────────────────────────────
export const healthApi = {
  check: () => axios.get(`${API_URL}/health`),
}

// ── Agent Settings ────────────────────────
export const agentSettingsApi = {
  update: (data: { use_flow_agent?: boolean; use_vision_agent?: boolean }) =>
    api.patch("/settings/agents", data),
}

// ── LLM Settings (local Ollama models + provider) ──
export const llmSettingsApi = {
  list: () => api.get("/settings/llms"),
  update: (data: {
    provider?: "ollama" | "claude" | "gateway" | "gemini"
    text_model?: string
    vision_model?: string
    gateway_model?: string
    gateway_vision_model?: string
    gemini_model?: string
    gemini_vision_model?: string
  }) => api.patch("/settings/llms", data),
  pull: (name: string) => api.post("/settings/llms/pull", { name }),
  remove: (name: string) => api.delete(`/settings/llms/${encodeURIComponent(name)}`),
}

export default api

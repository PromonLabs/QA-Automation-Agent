"use client"

import { useEffect, useState } from "react"
import { envApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import {
  Loader2, Save, Plus, Trash2, Eye, EyeOff,
  AlertCircle, CheckCircle2, Settings2, ShieldCheck,
  UserPlus, PhoneCall, DatabaseZap, CreditCard,
} from "lucide-react"

type EnvVar = { key: string; value: string }

// ── Section definitions (must match backend _ENV_SECTIONS) ──────────────────
const SECTIONS = [
  {
    id: "platform",
    title: "Platform Settings",
    subtitle: "Browser behaviour, LLM and screenshot options",
    icon: <Settings2 className="w-5 h-5" />,
    keys: ["SCREENSHOT_MODE","SKIP_LLM","BROWSER_HEADLESS","BROWSER_SLOW_MO","BROWSER_NAVIGATION_TIMEOUT","LLM_PROVIDER","LLM_MODEL","VISION_MODEL","CLAUDE_MODEL","ANTHROPIC_API_KEY"],
  },
  {
    id: "admin",
    title: "Shared Admin Credentials",
    subtitle: "Login credentials used across all flows",
    icon: <ShieldCheck className="w-5 h-5" />,
    keys: ["ADMIN_USER","ADMIN_PASS","ADMIN_EMAIL","ADMIN_PASSWORD","OPERATIONS_USER","OPERATIONS_PASS"],
  },
  {
    id: "flow1",
    title: "Flow 1 — New Account Creation",
    subtitle: "ICC inventory URL, CSR login and COS account",
    icon: <UserPlus className="w-5 h-5" />,
    keys: ["ICC_URL","CSR_USER","CSR_PASSWORD","ACCOUNT_NUMBER","MSITCOS_URL"],
  },
  {
    id: "flow2",
    title: "Flow 2 — Tusass TopUp Talk",
    subtitle: "COS URL, subscriber IDs and top-up amount",
    icon: <PhoneCall className="w-5 h-5" />,
    keys: ["COS_URL","PORTAL_URL","MISTIN_ID","PHONE_NUMBER","MOBILE_NUMBER","TOPUP_AMOUNT"],
  },
  {
    id: "flow3",
    title: "Flow 3 — Tusass Extra Data Add",
    subtitle: "Operations portal and data bundle amount",
    icon: <DatabaseZap className="w-5 h-5" />,
    keys: ["COS_OPERATION_URL","DATA_AMOUNT"],
  },
  {
    id: "card",
    title: "Payment Card Details",
    subtitle: "Test card used in checkout / payment steps",
    icon: <CreditCard className="w-5 h-5" />,
    keys: ["CARD_NUMBER","CARD_MONTH","CARD_YEAR","CARD_CVV","CARD_EXPIRY","CARD_CVC"],
  },
]

function isSensitive(key: string) {
  return /pass|secret|token|cvv|cvc|key|password/i.test(key)
}

// ── Per-section state ────────────────────────────────────────────────────────
type SectionState = { vars: EnvVar[]; showPwd: Record<number, boolean> }

function blankSection(keys: string[]): SectionState {
  return { vars: keys.map(k => ({ key: k, value: "" })), showPwd: {} }
}

function initSection(all: Record<string, string>, keys: string[]): SectionState {
  const vars = keys.map(k => ({ key: k, value: all[k.toUpperCase()] ?? "" }))
  return { vars, showPwd: {} }
}

// ── Section card component ───────────────────────────────────────────────────
function SectionCard({
  title, subtitle, icon, state,
  onChange, onAdd, onRemove, onTogglePwd,
}: {
  title: string
  subtitle: string
  icon: React.ReactNode
  state: SectionState
  onChange: (idx: number, field: "key" | "value", val: string) => void
  onAdd: () => void
  onRemove: (idx: number) => void
  onTogglePwd: (idx: number) => void
}) {
  return (
    <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5">
      <div className="flex items-center gap-3 mb-4">
        <span className="text-white/30">{icon}</span>
        <div>
          <h2 className="text-white font-semibold text-sm">{title}</h2>
          <p className="text-white/30 text-xs mt-0.5">{subtitle}</p>
        </div>
      </div>

      <div className="space-y-2">
        <div className="grid grid-cols-[1fr_1fr_32px] gap-2 pb-1.5 border-b border-white/5">
          <span className="text-white/20 text-[10px] uppercase tracking-widest pl-1">Variable</span>
          <span className="text-white/20 text-[10px] uppercase tracking-widest pl-1">Value</span>
          <span />
        </div>

        {state.vars.map((v, idx) => (
          <div key={idx} className="grid grid-cols-[1fr_1fr_32px] gap-2 items-center">
            <input
              value={v.key}
              onChange={e => onChange(idx, "key", e.target.value)}
              placeholder="VAR_NAME"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2
                         text-white text-xs font-mono placeholder-white/15
                         focus:outline-none focus:border-white/30 transition-colors"
            />
            <div className="relative">
              <input
                type={isSensitive(v.key) && !state.showPwd[idx] ? "password" : "text"}
                value={v.value}
                onChange={e => onChange(idx, "value", e.target.value)}
                placeholder="value"
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 pr-8
                           text-white text-xs font-mono placeholder-white/15
                           focus:outline-none focus:border-white/30 transition-colors"
              />
              {isSensitive(v.key) && (
                <button
                  type="button"
                  onClick={() => onTogglePwd(idx)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-white/25 hover:text-white/60"
                >
                  {state.showPwd[idx] ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                </button>
              )}
            </div>
            <button
              onClick={() => onRemove(idx)}
              className="flex items-center justify-center w-8 h-8 rounded-lg text-white/20
                         hover:text-red-400 hover:bg-red-500/10 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}

        <button
          onClick={onAdd}
          className="flex items-center gap-2 text-white/25 hover:text-white text-xs
                     border border-dashed border-white/10 hover:border-white/30
                     w-full py-2 rounded-lg transition-colors justify-center mt-1"
        >
          <Plus className="w-3.5 h-3.5" /> Add variable
        </button>
      </div>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function EnvPage() {
  const [sections, setSections] = useState<SectionState[]>(
    SECTIONS.map(s => blankSection(s.keys))
  )
  const [loading, setLoading] = useState(true)
  const [saving,  setSaving]  = useState(false)
  const [saved,   setSaved]   = useState(false)
  const [error,   setError]   = useState("")

  useEffect(() => {
    envApi.get()
      .then(r => {
        const all: Record<string, string> = {}
        ;(r.data as EnvVar[]).forEach(v => { all[v.key.trim().toUpperCase()] = v.value })
        setSections(SECTIONS.map(s => initSection(all, s.keys)))
      })
      .catch(() => setSections(SECTIONS.map(s => blankSection(s.keys))))
      .finally(() => setLoading(false))
  }, [])

  const updateSection = (si: number, idx: number, field: "key" | "value", val: string) =>
    setSections(prev => prev.map((s, i) =>
      i !== si ? s : {
        ...s,
        vars: s.vars.map((v, j) => j !== idx ? v : { ...v, [field]: val }),
      }
    ))

  const addVar = (si: number) =>
    setSections(prev => prev.map((s, i) =>
      i !== si ? s : { ...s, vars: [...s.vars, { key: "", value: "" }] }
    ))

  const removeVar = (si: number, idx: number) =>
    setSections(prev => prev.map((s, i) =>
      i !== si ? s : {
        ...s,
        vars: s.vars.length === 1 ? [{ key: "", value: "" }] : s.vars.filter((_, j) => j !== idx),
      }
    ))

  const togglePwd = (si: number, idx: number) =>
    setSections(prev => prev.map((s, i) =>
      i !== si ? s : { ...s, showPwd: { ...s.showPwd, [idx]: !s.showPwd[idx] } }
    ))

  const save = async () => {
    setSaving(true); setError("")
    try {
      const combined = sections.flatMap(s => s.vars).filter(v => v.key.trim())
      await envApi.save(combined)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to save .env")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-black">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Environment Variables" />
        <main className="flex-1 p-8 space-y-6 max-w-7xl">

          {/* Top bar */}
          <div className="flex items-center justify-between">
            <p className="text-white/30 text-sm">
              Saved to <code className="text-white/40">backend/.env</code> — applied on every flow run
            </p>
            <button
              onClick={save}
              disabled={saving}
              className="flex items-center gap-1.5 bg-white text-black text-sm font-semibold
                         px-5 py-2.5 rounded-lg hover:bg-white/90 transition-colors disabled:opacity-50"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> :
               saved   ? <CheckCircle2 className="w-4 h-4" /> :
                         <Save className="w-4 h-4" />}
              {saved ? "Saved!" : "Save"}
            </button>
          </div>

          {error && (
            <div className="flex items-center gap-2 px-4 py-3 bg-red-500/10 border
                            border-red-500/20 rounded-lg text-red-400 text-sm">
              <AlertCircle className="w-4 h-4 shrink-0" /> {error}
            </div>
          )}

          {loading ? (
            <div className="flex justify-center py-16">
              <Loader2 className="animate-spin text-white/20" />
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-5">
              {SECTIONS.map((def, si) => (
                <SectionCard
                  key={def.id}
                  title={def.title}
                  subtitle={def.subtitle}
                  icon={def.icon}
                  state={sections[si]}
                  onChange={(idx, field, val) => updateSection(si, idx, field, val)}
                  onAdd={() => addVar(si)}
                  onRemove={idx => removeVar(si, idx)}
                  onTogglePwd={idx => togglePwd(si, idx)}
                />
              ))}
            </div>
          )}

        </main>
      </div>
    </div>
  )
}

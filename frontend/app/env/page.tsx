"use client"

import { useEffect, useState } from "react"
import { envApi } from "@/lib/api"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import {
  Loader2, Save, Plus, Trash2, Eye, EyeOff,
  AlertCircle, CheckCircle2, KeyRound, CreditCard
} from "lucide-react"

type EnvVar = { key: string; value: string }

const CARD_KEYS = ["CARD_NUMBER", "CARD_MONTH", "CARD_YEAR", "CARD_CVV", "CARD_EXPIRY", "CARD_CVC"]

function isCardVar(key: string) {
  return key.toUpperCase().startsWith("CARD_")
}

function isPassword(key: string) {
  return /pass|secret|token|cvv|cvc|key/i.test(key)
}

interface SectionProps {
  title: string
  subtitle: string
  icon: React.ReactNode
  vars: EnvVar[]
  showPwd: Record<number, boolean>
  onUpdate: (idx: number, field: "key" | "value", val: string) => void
  onRemove: (idx: number) => void
  onAdd: () => void
  onTogglePwd: (idx: number) => void
}

function EnvSection({
  title, subtitle, icon, vars, showPwd,
  onUpdate, onRemove, onAdd, onTogglePwd,
}: SectionProps) {
  return (
    <div className="bg-white/[0.03] border border-white/10 rounded-xl p-6">
      <div className="flex items-center gap-3 mb-5">
        <div className="text-white/30">{icon}</div>
        <div>
          <h2 className="text-white font-semibold">{title}</h2>
          <p className="text-white/30 text-xs mt-0.5">{subtitle}</p>
        </div>
      </div>

      <div className="space-y-2">
        <div className="grid grid-cols-[1fr_1fr_36px] gap-3 pb-2 border-b border-white/5">
          <span className="text-white/30 text-xs uppercase tracking-widest pl-1">Variable Name</span>
          <span className="text-white/30 text-xs uppercase tracking-widest pl-1">Value</span>
          <span />
        </div>

        {vars.map((v, idx) => (
          <div key={idx} className="grid grid-cols-[1fr_1fr_36px] gap-3 items-center">
            <input
              value={v.key}
              onChange={e => onUpdate(idx, "key", e.target.value)}
              placeholder="VARIABLE_NAME"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2.5
                         text-white text-sm font-mono placeholder-white/15
                         focus:outline-none focus:border-white/30 transition-colors"
            />
            <div className="relative">
              <input
                type={isPassword(v.key) && !showPwd[idx] ? "password" : "text"}
                value={v.value}
                onChange={e => onUpdate(idx, "value", e.target.value)}
                placeholder="value"
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2.5 pr-9
                           text-white text-sm font-mono placeholder-white/15
                           focus:outline-none focus:border-white/30 transition-colors"
              />
              {isPassword(v.key) && (
                <button
                  type="button"
                  onClick={() => onTogglePwd(idx)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-white/25
                             hover:text-white/60 transition-colors"
                >
                  {showPwd[idx] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              )}
            </div>
            <button
              onClick={() => onRemove(idx)}
              className="flex items-center justify-center w-9 h-9 rounded-lg text-white/20
                         hover:text-red-400 hover:bg-red-500/10 transition-colors"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}

        <button
          onClick={onAdd}
          className="flex items-center gap-2 text-white/30 hover:text-white text-sm
                     border border-dashed border-white/10 hover:border-white/30
                     w-full py-2.5 rounded-lg transition-colors justify-center mt-2"
        >
          <Plus className="w-4 h-4" />
          Add variable
        </button>
      </div>
    </div>
  )
}

export default function EnvPage() {
  const [generalVars, setGeneralVars] = useState<EnvVar[]>([])
  const [cardVars, setCardVars]       = useState<EnvVar[]>([])
  const [loading, setLoading]         = useState(true)
  const [saving, setSaving]           = useState(false)
  const [saved, setSaved]             = useState(false)
  const [error, setError]             = useState("")
  const [showPwdG, setShowPwdG]       = useState<Record<number, boolean>>({})
  const [showPwdC, setShowPwdC]       = useState<Record<number, boolean>>({})

  useEffect(() => {
    envApi.get()
      .then(r => {
        const all: EnvVar[] = r.data.length ? r.data : []
        setGeneralVars(all.filter(v => !isCardVar(v.key)) .length ? all.filter(v => !isCardVar(v.key)) : [{ key: "", value: "" }])
        setCardVars(all.filter(v => isCardVar(v.key)).length ? all.filter(v => isCardVar(v.key)) : CARD_KEYS.map(k => ({ key: k, value: "" })))
      })
      .catch(() => {
        setGeneralVars([{ key: "", value: "" }])
        setCardVars(CARD_KEYS.map(k => ({ key: k, value: "" })))
      })
      .finally(() => setLoading(false))
  }, [])

  const updateGeneral = (idx: number, field: "key" | "value", val: string) =>
    setGeneralVars(prev => prev.map((v, i) => i === idx ? { ...v, [field]: val } : v))

  const updateCard = (idx: number, field: "key" | "value", val: string) =>
    setCardVars(prev => prev.map((v, i) => i === idx ? { ...v, [field]: val } : v))

  const removeGeneral = (idx: number) =>
    setGeneralVars(prev => prev.length === 1 ? [{ key: "", value: "" }] : prev.filter((_, i) => i !== idx))

  const removeCard = (idx: number) =>
    setCardVars(prev => prev.length === 1 ? [{ key: "", value: "" }] : prev.filter((_, i) => i !== idx))

  const save = async () => {
    setSaving(true); setError("")
    try {
      const combined = [
        ...generalVars.filter(v => v.key.trim()),
        ...cardVars.filter(v => v.key.trim()),
      ]
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
        <main className="flex-1 p-8 max-w-7xl space-y-6">

          {/* Save bar */}
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
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex justify-center py-16">
              <Loader2 className="animate-spin text-white/20" />
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-6 items-start">
              <EnvSection
                title="General Variables"
                subtitle="URLs, credentials, and runtime settings"
                icon={<KeyRound className="w-5 h-5" />}
                vars={generalVars}
                showPwd={showPwdG}
                onUpdate={updateGeneral}
                onRemove={removeGeneral}
                onAdd={() => setGeneralVars(prev => [...prev, { key: "", value: "" }])}
                onTogglePwd={idx => setShowPwdG(p => ({ ...p, [idx]: !p[idx] }))}
              />

              <EnvSection
                title="Card Details"
                subtitle="Payment card credentials used in checkout flows"
                icon={<CreditCard className="w-5 h-5" />}
                vars={cardVars}
                showPwd={showPwdC}
                onUpdate={updateCard}
                onRemove={removeCard}
                onAdd={() => setCardVars(prev => [...prev, { key: "", value: "" }])}
                onTogglePwd={idx => setShowPwdC(p => ({ ...p, [idx]: !p[idx] }))}
              />
            </div>
          )}

        </main>
      </div>
    </div>
  )
}

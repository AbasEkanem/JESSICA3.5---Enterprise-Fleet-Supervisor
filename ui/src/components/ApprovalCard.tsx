"use client";
import { useState, useCallback } from "react";
import { InterruptState } from "@/types/chat";

/* ──────────────────────────────────────────────────────────────────────────
   Tool metadata registry — maps tool names to display info
   ────────────────────────────────────────────────────────────────────────── */
const TOOL_META: Record<string, { icon: string; label: string; description: string }> = {
  send_research_email:      { icon: "📧", label: "Send Email",           description: "Compose and deliver an email message" },
  schedule_research_email:  { icon: "📅", label: "Schedule Email",       description: "Queue an email for later delivery" },
  send_slack_message:       { icon: "💬", label: "Send Slack Message",   description: "Post a message to a Slack channel" },
  send_slack_dm:            { icon: "📩", label: "Send Slack DM",        description: "Send a direct message on Slack" },
  transition_jira_issue:    { icon: "🔄", label: "Transition Jira Issue",description: "Change the status of a Jira ticket" },
  create_jira_issue:        { icon: "🎫", label: "Create Jira Issue",    description: "Open a new ticket in Jira" },
  update_jira_issue:        { icon: "✏️",  label: "Update Jira Issue",   description: "Modify an existing Jira ticket" },
  add_jira_comment:         { icon: "💭", label: "Add Jira Comment",     description: "Post a comment on a Jira ticket" },
};

const RISK_CONFIG = {
  high:   { border: "#f59e0b", badge: "HIGH RISK",   badgeColor: "#f59e0b", badgeBg: "rgba(245,158,11,0.12)" },
  medium: { border: "#6366f1", badge: "REVIEW",      badgeColor: "#6366f1", badgeBg: "rgba(99,102,241,0.12)" },
  low:    { border: "#22c55e", badge: "INFO",         badgeColor: "#22c55e", badgeBg: "rgba(34,197,94,0.12)"  },
};

export interface ApprovalCardProps {
  interrupt: InterruptState;
  onApprove: (editedArgs?: Record<string, unknown>) => Promise<void>;
  onReject: () => Promise<void>;
  disabled?: boolean;
}

/* 
   ApprovalCard Component
    */
export default function ApprovalCard({
  interrupt,
  onApprove,
  onReject,
  disabled = false,
}: ApprovalCardProps) {
  const meta    = TOOL_META[interrupt.tool] ?? { icon: "⚡", label: interrupt.tool, description: "Execute a tool action" };
  const riskCfg = RISK_CONFIG[interrupt.risk] ?? RISK_CONFIG.medium;

  const [phase,       setPhase]       = useState<"pending" | "approving" | "rejecting" | "approved" | "rejected">("pending");
  const [editMode,    setEditMode]    = useState(false);
  const [editedJson,  setEditedJson]  = useState(JSON.stringify(interrupt.args, null, 2));
  const [jsonError,   setJsonError]   = useState<string | null>(null);
  const [payloadOpen, setPayloadOpen] = useState(false);

  const handleApprove = useCallback(async () => {
    if (disabled || phase !== "pending") return;

    let finalArgs: Record<string, unknown> | undefined;
    if (editMode) {
      try {
        finalArgs = JSON.parse(editedJson);
        setJsonError(null);
      } catch (e: any) {
        setJsonError("Invalid JSON — fix the payload before approving.");
        return;
      }
    }
    setPhase("approving");
    try {
      await onApprove(finalArgs);
      setPhase("approved");
    } catch {
      setPhase("pending");
    }
  }, [disabled, phase, editMode, editedJson, onApprove]);

  const handleReject = useCallback(async () => {
    if (disabled || phase !== "pending") return;
    setPhase("rejecting");
    try {
      await onReject();
      setPhase("rejected");
    } catch {
      setPhase("pending");
    }
  }, [disabled, phase, onReject]);

  const isPending  = phase === "pending";
  const isActing   = phase === "approving" || phase === "rejecting";
  const isApproved = phase === "approved";
  const isRejected = phase === "rejected";
  const isDone     = isApproved || isRejected;

  /* ── Resolved states ── */
  if (isDone) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 16px",
          borderRadius: 12,
          border: `1px solid ${isApproved ? "rgba(34,197,94,0.25)" : "rgba(244,63,94,0.2)"}`,
          background: isApproved ? "rgba(34,197,94,0.06)" : "rgba(244,63,94,0.06)",
          animation: "hitlFadeIn 0.3s ease",
          marginBottom: 12,
          maxWidth: 560,
        }}
      >
        <span style={{ fontSize: 18 }}>{isApproved ? "✅" : "🚫"}</span>
        <span style={{ fontSize: 13, color: isApproved ? "#86efac" : "#fda4af" }}>
          {isApproved
            ? `${meta.icon} ${meta.label} approved — executing…`
            : `${meta.icon} ${meta.label} rejected — Jessica will stand down.`}
        </span>
      </div>
    );
  }

  /* ── Pending / acting state ── */
  return (
    <>
      <style>{`
        @keyframes hitlPulseBorder {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.5; }
        }
        @keyframes hitlFadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes hitlSlideUp {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes hitlSpin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        .hitl-approve-btn {
          transition: all 0.18s ease;
        }
        .hitl-approve-btn:hover:not(:disabled) {
          background: rgba(34,197,94,0.25) !important;
          transform: translateY(-1px);
          box-shadow: 0 4px 16px rgba(34,197,94,0.25);
        }
        .hitl-reject-btn {
          transition: all 0.18s ease;
        }
        .hitl-reject-btn:hover:not(:disabled) {
          background: rgba(244,63,94,0.12) !important;
          border-color: rgba(244,63,94,0.45) !important;
          color: #fda4af !important;
          transform: translateY(-1px);
        }
        .hitl-edit-btn {
          transition: all 0.18s ease;
        }
        .hitl-edit-btn:hover:not(:disabled) {
          background: rgba(255,255,255,0.07) !important;
          border-color: rgba(255,255,255,0.2) !important;
          transform: translateY(-1px);
        }
      `}</style>

      <div
        style={{
          maxWidth: 560,
          borderRadius: 16,
          border: `1.5px solid ${riskCfg.border}`,
          background: "rgba(14,14,20,0.88)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          boxShadow: `0 8px 40px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.04)`,
          marginBottom: 16,
          animation: `hitlSlideUp 0.35s cubic-bezier(0.34,1.56,0.64,1)`,
          animationFillMode: "both",
          ...(isPending && {
            animation: `hitlSlideUp 0.35s cubic-bezier(0.34,1.56,0.64,1), hitlPulseBorder 2.5s ease-in-out infinite`,
          }),
          overflow: "hidden",
          opacity: isActing ? 0.75 : 1,
          pointerEvents: isActing ? "none" : "auto",
          transition: "opacity 0.2s ease",
        }}
      >
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "12px 16px 10px",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
            background: "rgba(255,255,255,0.02)",
          }}
        >
          <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", color: "rgba(255,255,255,0.45)", textTransform: "uppercase" }}>
            ⚡ Jessica wants to take an action
          </span>
          <div style={{ flex: 1 }} />
          <span
            style={{
              fontSize: 10, fontWeight: 700, letterSpacing: "0.07em",
              color: riskCfg.badgeColor,
              background: riskCfg.badgeBg,
              border: `1px solid ${riskCfg.badgeColor}40`,
              borderRadius: 99, padding: "2px 8px",
              textTransform: "uppercase",
            }}
          >
            {riskCfg.badge}
          </span>
        </div>

        {/* ── Tool info ───────────────────────────────────────────────────── */}
        <div style={{ padding: "14px 16px 12px", display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div
            style={{
              width: 40, height: 40, borderRadius: 10, flexShrink: 0,
              background: riskCfg.badgeBg,
              border: `1px solid ${riskCfg.badgeColor}30`,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 20,
            }}
          >
            {meta.icon}
          </div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14.5, color: "rgba(255,255,255,0.9)", marginBottom: 2 }}>
              {meta.label}
            </div>
            <div style={{ fontSize: 12, color: "rgba(255,255,255,0.4)" }}>
              {meta.description}
            </div>
          </div>
        </div>

        {/* ── Arg preview (collapsible) ───────────────────────────────────── */}
        {Object.keys(interrupt.args).length > 0 && (
          <div style={{ padding: "0 16px 12px" }}>
            <button
              onClick={() => setPayloadOpen(v => !v)}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)",
                borderRadius: 8, padding: "6px 12px",
                cursor: "pointer", fontSize: 12, color: "rgba(255,255,255,0.55)",
                fontFamily: "inherit", width: "100%",
                transition: "background 0.15s",
              }}
            >
              <span style={{ transform: payloadOpen ? "rotate(90deg)" : "rotate(0deg)", display: "inline-block", transition: "transform 0.2s" }}>
                ▶
              </span>
              {payloadOpen ? "Hide" : "Preview"} payload
              {!payloadOpen && (
                <span style={{ marginLeft: "auto", fontFamily: "monospace", fontSize: 11, opacity: 0.6 }}>
                  {Object.keys(interrupt.args).slice(0, 2).join(", ")}{Object.keys(interrupt.args).length > 2 ? "…" : ""}
                </span>
              )}
            </button>

            {payloadOpen && (
              <div style={{ marginTop: 8 }}>
                {editMode ? (
                  <>
                    <textarea
                      value={editedJson}
                      onChange={e => { setEditedJson(e.target.value); setJsonError(null); }}
                      style={{
                        width: "100%", minHeight: 120,
                        background: "rgba(0,0,0,0.4)", border: "1px solid rgba(255,255,255,0.1)",
                        borderRadius: 8, padding: "10px 12px",
                        color: "#a5f3fc", fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                        fontSize: 12, lineHeight: 1.6, resize: "vertical", outline: "none",
                      }}
                    />
                    {jsonError && (
                      <div style={{ color: "#fda4af", fontSize: 11.5, marginTop: 4 }}>
                        ⚠ {jsonError}
                      </div>
                    )}
                  </>
                ) : (
                  /* Arg table ── field-by-field breakdown */
                  <div
                    style={{
                      background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.07)",
                      borderRadius: 8, overflow: "hidden",
                    }}
                  >
                    {Object.entries(interrupt.args).map(([key, val], idx) => (
                      <div
                        key={key}
                        style={{
                          display: "flex", gap: 10,
                          padding: "8px 12px",
                          borderBottom: idx < Object.keys(interrupt.args).length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none",
                        }}
                      >
                        <span style={{ fontFamily: "monospace", fontSize: 11.5, color: "rgba(255,255,255,0.4)", width: 90, flexShrink: 0, paddingTop: 1 }}>
                          {key}
                        </span>
                        <span
                          style={{
                            fontSize: 12.5, color: "rgba(255,255,255,0.75)",
                            wordBreak: "break-word", lineHeight: 1.5,
                            maxHeight: 72, overflowY: "auto",
                          }}
                        >
                          {typeof val === "string" ? val : JSON.stringify(val, null, 2)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Divider ──────────────────────────────────────────────────────── */}
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", margin: "0 16px" }} />

        {/* ── Action buttons ───────────────────────────────────────────────── */}
        <div style={{ display: "flex", gap: 8, padding: "12px 16px" }}>
          {/* Edit toggle */}
          <button
            className="hitl-edit-btn"
            onClick={() => { setEditMode(v => !v); setPayloadOpen(true); }}
            disabled={isActing}
            style={{
              flex: 1, padding: "9px 0",
              background: editMode ? "rgba(99,102,241,0.12)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${editMode ? "rgba(99,102,241,0.4)" : "rgba(255,255,255,0.1)"}`,
              borderRadius: 10, color: editMode ? "#a5b4fc" : "rgba(255,255,255,0.55)",
              fontSize: 13, fontWeight: 500, cursor: "pointer", fontFamily: "inherit",
            }}
          >
            ✏️ {editMode ? "Editing…" : "Edit"}
          </button>

          {/* Reject */}
          <button
            className="hitl-reject-btn"
            onClick={handleReject}
            disabled={isActing}
            style={{
              flex: 1, padding: "9px 0",
              background: "rgba(244,63,94,0.06)", border: "1px solid rgba(244,63,94,0.2)",
              borderRadius: 10, color: "rgba(255,255,255,0.55)",
              fontSize: 13, fontWeight: 500, cursor: "pointer", fontFamily: "inherit",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            }}
          >
            {phase === "rejecting"
              ? <span style={{ width: 14, height: 14, border: "2px solid #fda4af", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "hitlSpin 0.7s linear infinite" }} />
              : "✗ Reject"}
          </button>

          {/* Approve */}
          <button
            className="hitl-approve-btn"
            onClick={handleApprove}
            disabled={isActing}
            style={{
              flex: 2, padding: "9px 0",
              background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.35)",
              borderRadius: 10, color: "#86efac",
              fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            }}
          >
            {phase === "approving"
              ? <span style={{ width: 14, height: 14, border: "2px solid #86efac", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "hitlSpin 0.7s linear infinite" }} />
              : <><span>✓</span> Approve &amp; Execute</>}
          </button>
        </div>
      </div>
    </>
  );
}

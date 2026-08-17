import { useCallback, useEffect, useMemo, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import {
  Activity,
  AlertTriangle,
  Bot,
  Check,
  Clock,
  Copy,
  MessageSquare,
  RefreshCw,
  Search,
  ShieldCheck,
  User,
  Wrench,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface AuditSessionRecord {
  _file_path: string;
  key: string;
  node_type: "guide" | "primary";
  node_label: string;
  created_at: string;
  updated_at: string;
  messages: Array<{
    role?: string;
    content?: string;
    timestamp?: string;
    [key: string]: unknown;
  }>;
  metadata?: Record<string, unknown>;
}

export function AuditSessionsView() {
  const { getToken, token: contextToken } = useClient();
  const [sessions, setSessions] = useState<AuditSessionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [channelFilter, setChannelFilter] = useState<string>("all");
  const [nodeFilter, setNodeFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<"updated_desc" | "updated_asc" | "messages_desc">("updated_desc");
  const [copiedKey, setCopiedKey] = useState(false);

  const fetchAuditData = useCallback(async () => {
    setLoading(true);
    try {
      let activeToken = contextToken || "";
      if (getToken) {
        try {
          const fresh = await getToken();
          if (fresh) activeToken = fresh;
        } catch {
          // Fall back to context token
        }
      }

      const headers: Record<string, string> = {};
      if (activeToken) {
        headers["Authorization"] = `Bearer ${activeToken}`;
      }

      const urls = [
        "/api/v1/audit_sessions?action=list&timeframe=all",
        "/v1/audit_sessions?action=list&timeframe=all",
      ];

      for (const url of urls) {
        try {
          const res = await fetch(url, { headers, credentials: "same-origin" });
          if (res.ok) {
            const data = await res.json();
            if (Array.isArray(data.sessions)) {
              setSessions(data.sessions);
              if (data.sessions.length > 0 && !selectedKey) {
                setSelectedKey(data.sessions[0].key);
              }
              break;
            }
          }
        } catch {
          // Try next endpoint fallback
        }
      }
    } catch (e: unknown) {
      console.warn("Guide audit fetch notice:", e);
    } finally {
      setLoading(false);
    }
  }, [selectedKey, contextToken, getToken]);

  useEffect(() => {
    fetchAuditData();
  }, [fetchAuditData]);

  const filteredSessions = useMemo(() => {
    const matched = sessions.filter((s) => {
      const matchesSearch =
        !searchQuery ||
        s.key.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s._file_path.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.messages.some((m) =>
          String(m.content || "")
            .toLowerCase()
            .includes(searchQuery.toLowerCase())
        );

      const matchesChannel =
        channelFilter === "all" ||
        s.key.toLowerCase().includes(channelFilter.toLowerCase());

      const isGuide =
        s.node_type === "guide" ||
        s.node_label.toLowerCase().includes("guide") ||
        s.key.toLowerCase().includes(":guide:") ||
        s.key.toLowerCase().includes("guide");

      const matchesNode =
        nodeFilter === "all" ||
        (nodeFilter === "guide" ? isGuide : !isGuide);

      return matchesSearch && matchesChannel && matchesNode;
    });

    return matched.sort((a, b) => {
      if (sortBy === "updated_asc") {
        return (a.updated_at || a.created_at || "").localeCompare(b.updated_at || b.created_at || "");
      }
      if (sortBy === "messages_desc") {
        return b.messages.length - a.messages.length;
      }
      // Default: Most recently modified first ("updated_desc")
      return (b.updated_at || b.created_at || "").localeCompare(a.updated_at || a.created_at || "");
    });
  }, [sessions, searchQuery, channelFilter, nodeFilter, sortBy]);

  const activeSession = useMemo(() => {
    return filteredSessions.find((s) => s.key === selectedKey) || filteredSessions[0] || null;
  }, [filteredSessions, selectedKey]);

  const metrics = useMemo(() => {
    const total = sessions.length;
    const activeToday = sessions.filter((s) => {
      const today = new Date().toISOString().slice(0, 10);
      return (s.updated_at || "").startsWith(today);
    }).length;
    const totalTurns = sessions.reduce((acc, s) => acc + s.messages.length, 0);
    const flagged = sessions.filter((s) =>
      s.messages.some(
        (m) =>
          (m.role === "assistant" && !String(m.content || "").trim()) ||
          /(?:error|exception|failed|confused|wrong|invalid)/i.test(
            String(m.content || "")
          )
      )
    ).length;

    return { total, activeToday, totalTurns, flagged };
  }, [sessions]);

  const handleCopyTranscript = () => {
    if (!activeSession) return;
    const text = activeSession.messages
      .map(
        (m) =>
          `[${(m.timestamp || "").slice(0, 19)}] ${(m.role || "UNKNOWN").toUpperCase()}:\n${m.content || ""}`
      )
      .join("\n\n");
    navigator.clipboard.writeText(text);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 2000);
  };

  return (
    <div className="flex h-full w-full flex-col bg-background text-foreground overflow-hidden">
      {/* Top Header & Metrics Bar */}
      <div className="flex shrink-0 flex-col gap-4 border-b border-border bg-card/50 p-4 lg:px-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">
                Sessions
              </h1>
              <p className="text-xs text-muted-foreground">
                Inspect, search, and audit session logs across all channels and nodes.
              </p>
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={fetchAuditData}
            disabled={loading}
            className="gap-2 text-xs"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>

        {/* Metric Cards */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="flex flex-col gap-1 rounded-xl border border-border/60 bg-background/60 p-3">
            <span className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-primary" /> Evaluated Sessions
            </span>
            <span className="text-xl font-bold tracking-tight text-foreground">
              {metrics.total}
            </span>
          </div>

          <div className="flex flex-col gap-1 rounded-xl border border-border/60 bg-background/60 p-3">
            <span className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-emerald-500" /> Active Today
            </span>
            <span className="text-xl font-bold tracking-tight text-emerald-400">
              {metrics.activeToday}
            </span>
          </div>

          <div className="flex flex-col gap-1 rounded-xl border border-border/60 bg-background/60 p-3">
            <span className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <MessageSquare className="h-3.5 w-3.5 text-sky-500" /> Total Turns
            </span>
            <span className="text-xl font-bold tracking-tight text-sky-400">
              {metrics.totalTurns}
            </span>
          </div>

          <div className="flex flex-col gap-1 rounded-xl border border-border/60 bg-background/60 p-3">
            <span className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-500" /> Flagged Queries
            </span>
            <span className="text-xl font-bold tracking-tight text-amber-400">
              {metrics.flagged}
            </span>
          </div>
        </div>
      </div>

      {/* Main Dual Pane Content Area */}
      <div className="flex flex-1 min-h-0 divide-x divide-border">
        {/* Left Session List Column */}
        <div className="flex w-80 shrink-0 flex-col bg-sidebar/30">
          {/* Filter Bar */}
          <div className="flex flex-col gap-2.5 p-3 border-b border-border">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search session key or text..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8 pl-8 text-xs bg-background/80"
              />
            </div>

            {/* Channel Filters */}
            <div className="flex flex-wrap gap-1">
              {["all", "whatsapp", "telegram", "web", "api"].map((ch) => (
                <button
                  key={ch}
                  onClick={() => setChannelFilter(ch)}
                  className={cn(
                    "rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors capitalize",
                    channelFilter === ch
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted/60 text-muted-foreground hover:bg-muted"
                  )}
                >
                  {ch}
                </button>
              ))}
            </div>

            {/* Node Workspace Filters */}
            <div className="flex gap-1">
              {[
                { key: "all", label: "All Nodes" },
                { key: "guide", label: "Guide Node" },
                { key: "primary", label: "Primary Node" },
              ].map((n) => (
                <button
                  key={n.key}
                  onClick={() => setNodeFilter(n.key)}
                  className={cn(
                    "flex-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium transition-colors text-center",
                    nodeFilter === n.key
                      ? "bg-secondary text-secondary-foreground font-semibold"
                      : "bg-muted/40 text-muted-foreground hover:bg-muted/80"
                  )}
                >
                  {n.label}
                </button>
              ))}
            </div>

            {/* Sort Order Selector */}
            <div className="flex items-center justify-between gap-1 pt-1 text-[11px] text-muted-foreground">
              <span>Sort:</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as "updated_desc" | "updated_asc" | "messages_desc")}
                className="rounded-md border border-border bg-background px-2 py-0.5 text-[11px] text-foreground focus:outline-none cursor-pointer"
              >
                <option value="updated_desc">Most Recent</option>
                <option value="updated_asc">Oldest First</option>
                <option value="messages_desc">Most Messages</option>
              </select>
            </div>
          </div>

          {/* Session Cards List */}
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {filteredSessions.length === 0 ? (
              <div className="p-6 text-center text-xs text-muted-foreground">
                No matching sessions found.
              </div>
            ) : (
              filteredSessions.map((s) => {
                const isSelected = activeSession?.key === s.key;
                const isGuide = s.node_type === "guide" || s.node_label.includes("Guide");

                return (
                  <button
                    key={s.key}
                    onClick={() => setSelectedKey(s.key)}
                    className={cn(
                      "w-full text-left rounded-lg p-2.5 transition-colors border",
                      isSelected
                        ? "bg-accent/80 border-primary/40 text-accent-foreground shadow-sm"
                        : "bg-card/40 border-border/40 hover:bg-muted/50 text-foreground"
                    )}
                  >
                    <div className="flex items-center justify-between gap-1 mb-1">
                      <span
                        className={cn(
                          "px-1.5 py-0.5 rounded text-[9.5px] font-semibold tracking-wide uppercase border",
                          isGuide
                            ? "bg-purple-500/15 text-purple-400 border-purple-500/30"
                            : "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                        )}
                      >
                        {s.node_label || (isGuide ? "Guide Node" : "Primary Node")}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {(s.updated_at || "").slice(5, 16).replace("T", " ")}
                      </span>
                    </div>

                    <div className="truncate text-xs font-mono font-medium text-foreground mb-1">
                      {s.key}
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                      <span>{s.messages.length} msgs</span>
                      <span className="capitalize text-[10px] font-semibold px-1 bg-muted rounded">
                        {s.key.includes("whatsapp")
                          ? "whatsapp"
                          : s.key.includes("telegram")
                          ? "telegram"
                          : "web"}
                      </span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Right Transcript Inspection Pane */}
        <div className="flex flex-1 flex-col overflow-hidden bg-background">
          {activeSession ? (
            <>
              {/* Active Session Header */}
              <div className="flex shrink-0 items-center justify-between border-b border-border bg-card/30 p-3.5 px-6">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <h2 className="text-sm font-mono font-semibold truncate text-foreground">
                      {activeSession.key}
                    </h2>
                    <span
                      className={cn(
                        "px-2 py-0.5 rounded-full text-[10px] font-medium border",
                        activeSession.node_type === "guide" || activeSession.node_label.includes("Guide")
                          ? "bg-purple-500/15 text-purple-400 border-purple-500/30"
                          : "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                      )}
                    >
                      {activeSession.node_label}
                    </span>
                  </div>
                  <p className="text-[11px] text-muted-foreground truncate">
                    Path: <code className="text-[10.5px]">{activeSession._file_path}</code>
                  </p>
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCopyTranscript}
                  className="gap-1.5 text-xs shrink-0"
                >
                  {copiedKey ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                  {copiedKey ? "Copied" : "Copy Thread"}
                </Button>
              </div>

              {/* Message Transcript Thread */}
              <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
                {activeSession.messages.length === 0 ? (
                  <div className="p-12 text-center text-xs text-muted-foreground">
                    No message turns recorded in this session.
                  </div>
                ) : (
                  activeSession.messages.map((m, idx) => {
                    const role = String(m.role || "user").toLowerCase();
                    const isUser = role === "user";
                    const isAssistant = role === "assistant";
                    const ts = String(m.timestamp || "").slice(0, 19).replace("T", " ");

                    return (
                      <div
                        key={idx}
                        className={cn(
                          "flex flex-col gap-1.5 rounded-xl p-3.5 border transition-all max-w-3xl",
                          isUser
                            ? "bg-sky-950/20 border-sky-500/20 mr-auto"
                            : isAssistant
                            ? "bg-emerald-950/20 border-emerald-500/20 ml-auto"
                            : "bg-purple-950/20 border-purple-500/20 mx-auto w-full"
                        )}
                      >
                        <div className="flex items-center justify-between text-[11px] font-semibold border-b border-border/40 pb-1.5 mb-1">
                          <span className="flex items-center gap-1.5">
                            {isUser ? (
                              <User className="h-3.5 w-3.5 text-sky-400" />
                            ) : isAssistant ? (
                              <Bot className="h-3.5 w-3.5 text-emerald-400" />
                            ) : (
                              <Zap className="h-3.5 w-3.5 text-purple-400" />
                            )}
                            <span className={cn(isUser ? "text-sky-400" : isAssistant ? "text-emerald-400" : "text-purple-400")}>
                              {role.toUpperCase()}
                            </span>
                          </span>
                          <span className="text-[10px] text-muted-foreground font-mono">
                            {ts}
                          </span>
                        </div>

                        {/* Text Content */}
                        {m.content ? (
                          <div className="text-xs leading-relaxed whitespace-pre-wrap font-sans text-foreground">
                            {String(m.content)}
                          </div>
                        ) : null}

                        {/* Assistant Tool Calls */}
                        {Array.isArray(m.tool_calls) && m.tool_calls.length > 0 && (
                          <div className="mt-1 flex flex-col gap-1.5 rounded-lg border border-purple-500/30 bg-purple-950/30 p-2.5">
                            <div className="flex items-center gap-1.5 text-[11px] font-semibold text-purple-300">
                              <Wrench className="h-3.5 w-3.5 text-purple-400" />
                              <span>Tool Call{m.tool_calls.length > 1 ? "s" : ""}</span>
                            </div>
                            {m.tool_calls.map((tc, tcIdx) => {
                              const tcObj = typeof tc === "object" && tc !== null ? (tc as Record<string, unknown>) : {};
                              const fnObj = typeof tcObj.function === "object" && tcObj.function !== null ? (tcObj.function as Record<string, unknown>) : tcObj;
                              const fnName = String(fnObj.name || tcObj.name || "tool");
                              const rawArgs = fnObj.arguments ?? tcObj.arguments;
                              const argsStr =
                                typeof rawArgs === "object" && rawArgs !== null
                                  ? JSON.stringify(rawArgs, null, 2)
                                  : String(rawArgs || "");
                              const tcId = typeof tcObj.id === "string" ? tcObj.id : undefined;
                              return (
                                <div key={tcIdx} className="flex flex-col gap-1 font-mono text-[11px]">
                                  <div className="font-semibold text-purple-200 flex items-center gap-1.5">
                                    <span className="rounded bg-purple-500/20 px-1.5 py-0.5">{fnName}</span>
                                    {tcId && <span className="text-[10px] text-purple-300/60">({tcId})</span>}
                                  </div>
                                  {argsStr && (
                                    <pre className="overflow-x-auto rounded border border-purple-500/20 bg-black/50 p-2 text-[10.5px] text-purple-200/90 whitespace-pre-wrap break-all max-h-48">
                                      {argsStr}
                                    </pre>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}

                        {/* Fallback if both text content and tool_calls are empty */}
                        {!m.content && (!Array.isArray(m.tool_calls) || m.tool_calls.length === 0) && (
                          <div className="text-xs italic text-muted-foreground">
                            (No text content)
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
              Select a session from the left sidebar to view its transcript.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

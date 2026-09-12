import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import {
  Bot,
  CheckCircle2,
  GitBranch,
  Play,
  RotateCcw,
  Sparkles,
  Terminal,
  XCircle,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { WorkflowNodeData } from "./workflow-layout";

export const StartNode = memo(function StartNode() {
  return (
    <div className="flex items-center gap-2 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 shadow-sm backdrop-blur-md dark:border-emerald-500/30 dark:bg-emerald-950/40">
      <Play className="h-4 w-4 fill-emerald-500 text-emerald-500" />
      <span className="text-xs font-bold tracking-wider text-emerald-600 dark:text-emerald-400">
        START
      </span>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-2.5 !w-2.5 !border-2 !border-emerald-500 !bg-background"
      />
    </div>
  );
});

export const WorkflowStateNode = memo(function WorkflowStateNode({
  data,
}: {
  data: WorkflowNodeData;
}) {
  const { stateName, state, stepRecord, isSelected, isStart } = data;
  const stateType = "type" in state ? state.type : "unknown";

  const isTask = stateType === "task";
  const isChoice = stateType === "choice";
  const isPass = stateType === "pass";
  const isFail = stateType === "fail";
  const isSucceed = stateType === "succeed";

  const isTerminal = ("end" in state && state.end) || isFail || isSucceed;

  // Run execution status
  const runStatus = stepRecord?.status;
  const isRunSuccess = runStatus === "succeeded";
  const isRunFailed = runStatus === "failed" || runStatus === "timed_out";

  const getActionIcon = () => {
    if (isChoice) return <GitBranch className="h-4 w-4 text-purple-500" />;
    if (isPass) return <RotateCcw className="h-4 w-4 text-cyan-500" />;
    if (isFail) return <XCircle className="h-4 w-4 text-rose-500" />;
    if (isSucceed) return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
    if (stateType === "llm" || (isTask && "action" in state && state.action === "prompt")) {
      return <Sparkles className="h-4 w-4 text-amber-500" />;
    }
    if (stateType === "exec" || (isTask && "action" in state && state.action === "exec")) {
      return <Terminal className="h-4 w-4 text-sky-500" />;
    }
    if (stateType === "tool" || (isTask && "action" in state && state.action === "tool")) {
      return <Bot className="h-4 w-4 text-blue-500" />;
    }
    return <Bot className="h-4 w-4 text-muted-foreground" />;
  };

  const getTypeBadge = () => {
    if (isChoice) {
      return (
        <span className="rounded bg-purple-500/10 px-1.5 py-0.5 text-[10px] font-medium text-purple-600 dark:text-purple-300">
          Choice
        </span>
      );
    }
    if (stateType === "llm") {
      return (
        <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-300">
          LLM
        </span>
      );
    }
    if (stateType === "exec") {
      return (
        <span className="rounded bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-medium text-sky-600 dark:text-sky-300">
          Exec
        </span>
      );
    }
    if (stateType === "tool") {
      return (
        <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-600 dark:text-blue-300">
          Tool
        </span>
      );
    }
    if (isTask && "action" in state) {
      return (
        <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-600 dark:text-blue-300">
          {state.action}
        </span>
      );
    }
    if (isPass) {
      return (
        <span className="rounded bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-medium text-cyan-600 dark:text-cyan-300">
          Pass
        </span>
      );
    }
    if (isFail) {
      return (
        <span className="rounded bg-rose-500/10 px-1.5 py-0.5 text-[10px] font-medium text-rose-600 dark:text-rose-300">
          Fail
        </span>
      );
    }
    if (isSucceed) {
      return (
        <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-300">
          Succeed
        </span>
      );
    }
    return null;
  };

  return (
    <div
      className={cn(
        "group relative w-[240px] rounded-xl border bg-card p-3 shadow-sm transition-all hover:shadow-md cursor-pointer",
        isSelected
          ? "border-primary ring-2 ring-primary/30"
          : "border-border hover:border-foreground/30",
        isRunSuccess && "!border-emerald-500/60 ring-1 ring-emerald-500/30",
        isRunFailed && "!border-rose-500/60 ring-1 ring-rose-500/30",
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-2.5 !w-2.5 !border-2 !border-primary/60 !bg-background"
      />

      <div className="flex items-center justify-between gap-1.5">
        <div className="flex items-center gap-2 overflow-hidden">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted/70">
            {getActionIcon()}
          </div>
          <span className="truncate text-xs font-semibold text-foreground" title={stateName}>
            {stateName}
          </span>
        </div>
        <div className="shrink-0">{getTypeBadge()}</div>
      </div>

      {/* Description or Comment */}
      {"comment" in state && state.comment ? (
        <p className="mt-2 line-clamp-1 text-[11px] text-muted-foreground" title={state.comment}>
          {state.comment}
        </p>
      ) : isTask && "prompt" in state && state.prompt ? (
        <p className="mt-2 line-clamp-1 font-mono text-[10.5px] text-muted-foreground" title={state.prompt}>
          {state.prompt}
        </p>
      ) : null}

      {/* Footer tags */}
      <div className="mt-2.5 flex items-center justify-between gap-1 border-t border-border/50 pt-2 text-[10px]">
        <div className="flex items-center gap-1.5 text-muted-foreground">
          {isStart && (
            <span className="rounded bg-emerald-500/10 px-1 py-0.2 text-[9px] font-semibold text-emerald-600">
              Entry
            </span>
          )}
          {isTerminal && (
            <span className="rounded bg-muted px-1 py-0.2 text-[9px] font-medium text-muted-foreground">
              End
            </span>
          )}
          {"result_path" in state && state.result_path && (
            <span className="truncate font-mono text-muted-foreground" title={state.result_path}>
              {state.result_path}
            </span>
          )}
        </div>

        {/* Execution step badge if available */}
        {stepRecord && (
          <div
            className={cn(
              "flex items-center gap-1 font-medium",
              isRunSuccess ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400",
            )}
          >
            <Clock className="h-3 w-3" />
            <span>{stepRecord.duration_ms.toFixed(0)}ms</span>
          </div>
        )}
      </div>

      {!isTerminal && (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!h-2.5 !w-2.5 !border-2 !border-primary/60 !bg-background"
        />
      )}
    </div>
  );
});

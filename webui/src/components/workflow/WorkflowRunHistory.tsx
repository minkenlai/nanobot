import { CheckCircle2, Clock, History, RotateCcw, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { WorkflowRunRecord } from "@/lib/types";

interface WorkflowRunHistoryProps {
  runs: WorkflowRunRecord[];
  selectedRunId?: string | null;
  onSelectRun: (run: WorkflowRunRecord | null) => void;
  onRefresh: () => void;
  loading?: boolean;
}

export function WorkflowRunHistory({
  runs,
  selectedRunId,
  onSelectRun,
  onRefresh,
  loading,
}: WorkflowRunHistoryProps) {
  return (
    <div className="flex h-full flex-col border-l border-border bg-card/95 backdrop-blur-sm">
      <div className="flex items-center justify-between border-b border-border/80 px-4 py-3">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-sm">Execution Runs</h3>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            {runs.length}
          </span>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0"
          onClick={onRefresh}
          disabled={loading}
          title="Refresh runs"
        >
          <RotateCcw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1 text-xs">
        {runs.length === 0 ? (
          <div className="p-4 text-center text-muted-foreground">
            No execution runs found. Click "Run Workflow" to execute.
          </div>
        ) : (
          runs.map((run) => {
            const isSelected = run.run_id === selectedRunId;
            const isSuccess = run.status === "succeeded";
            const isFailed = run.status === "failed" || run.status === "timed_out";
            const dateStr = new Date(run.start_time * 1000).toLocaleString(undefined, {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            });

            return (
              <button
                key={run.run_id}
                type="button"
                onClick={() => onSelectRun(isSelected ? null : run)}
                className={cn(
                  "w-full rounded-lg border p-2.5 text-left transition-colors cursor-pointer",
                  isSelected
                    ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                    : "border-border/60 hover:bg-muted/40",
                )}
              >
                <div className="flex items-center justify-between gap-1">
                  <div className="flex items-center gap-1.5 overflow-hidden">
                    {isSuccess ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                    ) : isFailed ? (
                      <XCircle className="h-3.5 w-3.5 text-rose-500 shrink-0" />
                    ) : (
                      <Clock className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                    )}
                    <span className="truncate font-mono text-[11px] font-semibold">
                      {run.run_id.slice(0, 12)}
                    </span>
                  </div>
                  <span className="text-[10px] text-muted-foreground shrink-0">
                    {run.total_duration_ms.toFixed(0)} ms
                  </span>
                </div>

                <div className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground">
                  <span>{dateStr}</span>
                  <span>{run.steps?.length ?? 0} step(s)</span>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

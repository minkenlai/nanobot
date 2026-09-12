import { CheckCircle2, Clock, Info, X, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type {
  StepExecutionRecord,
  WorkflowDefinition,
  WorkflowRunRecord,
  WorkflowState,
} from "@/lib/types";

interface WorkflowInspectorProps {
  stateName: string;
  workflow: WorkflowDefinition;
  selectedRun?: WorkflowRunRecord | null;
  onClose: () => void;
}

export function WorkflowInspector({
  stateName,
  workflow,
  selectedRun,
  onClose,
}: WorkflowInspectorProps) {
  const state: WorkflowState | undefined = workflow.states[stateName];

  // Find step in run
  const stepRecord: StepExecutionRecord | undefined = selectedRun?.steps?.find(
    (s) => s.state_name === stateName,
  );

  if (!state) {
    return null;
  }

  return (
    <div className="flex h-full flex-col border-l border-border bg-card/95 text-card-foreground shadow-lg backdrop-blur-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/80 px-4 py-3">
        <div className="flex items-center gap-2 overflow-hidden">
          <Info className="h-4 w-4 text-primary" />
          <h3 className="truncate font-semibold text-sm" title={stateName}>
            {stateName}
          </h3>
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono uppercase text-muted-foreground">
            {state.type}
          </span>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4 text-xs">
        {/* Run telemetry if present */}
        {stepRecord && (
          <div className="rounded-lg border border-border/80 bg-background/50 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-muted-foreground uppercase text-[10px]">
                Execution Telemetry (Step #{stepRecord.step_index + 1})
              </span>
              <span
                className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                  stepRecord.status === "succeeded"
                    ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    : "bg-rose-500/10 text-rose-600 dark:text-rose-400"
                }`}
              >
                {stepRecord.status === "succeeded" ? (
                  <CheckCircle2 className="h-3 w-3" />
                ) : (
                  <XCircle className="h-3 w-3" />
                )}
                {stepRecord.status}
              </span>
            </div>

            <div className="flex items-center gap-2 text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>Duration: {stepRecord.duration_ms.toFixed(1)} ms</span>
            </div>

            {stepRecord.error && (
              <div className="rounded bg-rose-500/10 p-2 text-rose-600 dark:text-rose-400 font-mono text-[11px]">
                {stepRecord.error}
              </div>
            )}

            {stepRecord.output !== undefined && (
              <div>
                <span className="text-[10px] font-medium text-muted-foreground">Step Output:</span>
                <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted/60 p-2 font-mono text-[10.5px]">
                  {typeof stepRecord.output === "object"
                    ? JSON.stringify(stepRecord.output, null, 2)
                    : String(stepRecord.output)}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* State definition details */}
        <div className="space-y-3">
          {"comment" in state && state.comment && (
            <div>
              <span className="text-[10px] font-medium text-muted-foreground">Description</span>
              <p className="mt-0.5 text-foreground">{state.comment}</p>
            </div>
          )}

          {state.type === "task" && (
            <>
              <div>
                <span className="text-[10px] font-medium text-muted-foreground">Action</span>
                <p className="mt-0.5 font-mono font-medium text-primary">{state.action}</p>
              </div>

              {state.prompt && (
                <div>
                  <span className="text-[10px] font-medium text-muted-foreground">Prompt Template</span>
                  <pre className="mt-0.5 whitespace-pre-wrap rounded bg-muted/60 p-2 font-mono text-[11px]">
                    {state.prompt}
                  </pre>
                </div>
              )}

              {state.params && Object.keys(state.params).length > 0 && (
                <div>
                  <span className="text-[10px] font-medium text-muted-foreground">Parameters</span>
                  <pre className="mt-0.5 max-h-36 overflow-auto rounded bg-muted/60 p-2 font-mono text-[10.5px]">
                    {JSON.stringify(state.params, null, 2)}
                  </pre>
                </div>
              )}

              {state.result_path && (
                <div>
                  <span className="text-[10px] font-medium text-muted-foreground">Result Path</span>
                  <p className="mt-0.5 font-mono text-muted-foreground">{state.result_path}</p>
                </div>
              )}
            </>
          )}

          {state.type === "choice" && (
            <div>
              <span className="text-[10px] font-medium text-muted-foreground">Choice Branches</span>
              <div className="mt-1 space-y-1.5">
                {state.choices?.map((c, i) => (
                  <div key={i} className="rounded border border-border/60 bg-muted/30 p-2 font-mono text-[11px]">
                    <div className="text-muted-foreground">When {c.variable}:</div>
                    <div className="text-primary font-medium pl-2">➔ Go to: {c.next}</div>
                  </div>
                ))}
                {state.default && (
                  <div className="rounded border border-border/60 bg-muted/30 p-2 font-mono text-[11px]">
                    <div className="text-muted-foreground">Default:</div>
                    <div className="text-primary font-medium pl-2">➔ Go to: {state.default}</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {"next" in state && state.next && (
            <div>
              <span className="text-[10px] font-medium text-muted-foreground">Next State</span>
              <p className="mt-0.5 font-mono font-medium text-primary">{state.next}</p>
            </div>
          )}

          {"end" in state && state.end && (
            <div className="rounded bg-muted/60 p-2 text-muted-foreground text-[11px]">
              This state terminates the workflow.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

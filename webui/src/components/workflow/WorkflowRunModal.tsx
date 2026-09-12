import { useState } from "react";
import { Play, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { WorkflowDefinition, WorkflowRunRecord } from "@/lib/types";
import { runWorkflow } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

interface WorkflowRunModalProps {
  workflow: WorkflowDefinition;
  onClose: () => void;
  onRunComplete: (record: WorkflowRunRecord) => void;
}

export function WorkflowRunModal({
  workflow,
  onClose,
  onRunComplete,
}: WorkflowRunModalProps) {
  const { client } = useClient();
  const [contextJson, setContextJson] = useState("{\n  \n}");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<WorkflowRunRecord | null>(null);

  const handleRun = async () => {
    setError(null);
    let parsedContext: Record<string, unknown> | undefined;
    if (contextJson.trim()) {
      try {
        parsedContext = JSON.parse(contextJson);
      } catch (err: any) {
        setError(`Invalid Initial Context JSON: ${err.message}`);
        return;
      }
    }

    setRunning(true);
    try {
      const resp = await runWorkflow(client, workflow.id, parsedContext);
      if (resp && resp.run) {
        setRunResult(resp.run);
        onRunComplete(resp.run);
      }
    } catch (err: any) {
      setError(err.message || "Execution failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
      <div className="relative w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-border/60 pb-3">
          <div>
            <h2 className="text-lg font-bold">Run Workflow: {workflow.name}</h2>
            <p className="text-xs text-muted-foreground">
              Workflow ID: <code className="font-mono">{workflow.id}</code>
            </p>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            ✕
          </Button>
        </div>

        {error && (
          <div className="rounded-lg bg-rose-500/10 p-3 text-xs text-rose-600 dark:text-rose-400 font-mono">
            {error}
          </div>
        )}

        {runResult ? (
          <div className="space-y-3 rounded-lg border border-border/80 bg-background/60 p-4 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-sm">Execution Completed</span>
              <span
                className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
                  runResult.status === "succeeded"
                    ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    : "bg-rose-500/10 text-rose-600 dark:text-rose-400"
                }`}
              >
                {runResult.status === "succeeded" ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {runResult.status}
              </span>
            </div>

            <div className="text-muted-foreground space-y-1">
              <div>Run ID: <span className="font-mono text-foreground">{runResult.run_id}</span></div>
              <div>Duration: <span className="font-mono text-foreground">{runResult.total_duration_ms.toFixed(1)}ms</span></div>
              <div>Steps Executed: <span className="font-mono text-foreground">{runResult.steps.length}</span></div>
            </div>

            {runResult.error && (
              <div className="rounded bg-rose-500/10 p-2 text-rose-600 dark:text-rose-400 font-mono">
                {runResult.error}
              </div>
            )}

            <div>
              <span className="font-medium text-muted-foreground">Final Context:</span>
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted/60 p-2 font-mono text-[10.5px]">
                {JSON.stringify(runResult.final_context, null, 2)}
              </pre>
            </div>

            <div className="flex justify-end pt-2">
              <Button type="button" size="sm" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold mb-1 text-muted-foreground">
                Initial Context (JSON Optional)
              </label>
              <textarea
                rows={6}
                value={contextJson}
                onChange={(e) => setContextJson(e.target.value)}
                className="w-full rounded-lg border border-border bg-muted/40 p-2.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="{}"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={running}>
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                className="gap-1.5"
                onClick={handleRun}
                disabled={running}
              >
                {running ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Executing...</span>
                  </>
                ) : (
                  <>
                    <Play className="h-3.5 w-3.5 fill-current" />
                    <span>Run Now</span>
                  </>
                )}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

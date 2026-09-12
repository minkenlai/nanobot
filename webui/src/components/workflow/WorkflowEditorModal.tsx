import { useState } from "react";
import { Save, AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { WorkflowDefinition } from "@/lib/types";
import { saveWorkflow } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

interface WorkflowEditorModalProps {
  initialWorkflow?: WorkflowDefinition | null;
  onClose: () => void;
  onSaveComplete: (saved: WorkflowDefinition) => void;
}

const DEFAULT_WORKFLOW_TEMPLATE: WorkflowDefinition = {
  id: "sample_workflow",
  name: "Sample Workflow",
  description: "A declarative state machine workflow",
  trigger: {
    cron: "0 9 * * *",
    tz: "UTC",
    enabled: true,
  },
  start_at: "FetchData",
  states: {
    FetchData: {
      type: "task",
      action: "prompt",
      prompt: "Summarize top priorities for today based on active projects.",
      result_path: "$.summary",
      next: "CheckSummary",
    },
    CheckSummary: {
      type: "choice",
      choices: [
        {
          variable: "$.summary",
          contains: "URGENT",
          next: "NotifyUrgent",
        },
      ],
      default: "Done",
    },
    NotifyUrgent: {
      type: "task",
      action: "send_message",
      params: {
        message: "🚨 Urgent items detected: {{$.summary}}",
      },
      end: true,
    },
    Done: {
      type: "pass",
      comment: "Workflow finished successfully",
      end: true,
    },
  },
};

export function WorkflowEditorModal({
  initialWorkflow,
  onClose,
  onSaveComplete,
}: WorkflowEditorModalProps) {
  const { client } = useClient();
  const [jsonText, setJsonText] = useState(() =>
    JSON.stringify(initialWorkflow || DEFAULT_WORKFLOW_TEMPLATE, null, 2),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setError(null);
    let parsed: any;
    try {
      parsed = JSON.parse(jsonText);
    } catch (err: any) {
      setError(`Invalid JSON syntax: ${err.message}`);
      return;
    }

    if (!parsed.id || typeof parsed.id !== "string") {
      setError("Workflow definition must contain a string 'id'");
      return;
    }
    if (!parsed.start_at || !parsed.states || typeof parsed.states !== "object") {
      setError("Workflow definition must have 'start_at' and 'states' object");
      return;
    }

    setSaving(true);
    try {
      const resp = await saveWorkflow(client, parsed as WorkflowDefinition);
      if (resp && resp.workflow) {
        onSaveComplete(resp.workflow);
        onClose();
      }
    } catch (err: any) {
      setError(err.message || "Failed to save workflow");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
      <div className="relative flex h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-border bg-card shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between border-b border-border/70 px-6 py-4">
          <div>
            <h2 className="text-base font-bold">
              {initialWorkflow ? `Edit Workflow: ${initialWorkflow.name}` : "Create New Workflow"}
            </h2>
            <p className="text-xs text-muted-foreground">
              Configure states, actions, conditional choice transitions, and triggers in Amazon States Language (ASL) format.
            </p>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            ✕
          </Button>
        </div>

        {error && (
          <div className="mx-6 mt-4 flex items-center gap-2 rounded-lg bg-rose-500/10 p-3 text-xs text-rose-600 dark:text-rose-400 font-mono">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex-1 p-6 overflow-hidden">
          <textarea
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            className="h-full w-full resize-none rounded-xl border border-border bg-muted/40 p-4 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-primary leading-relaxed"
            spellCheck={false}
          />
        </div>

        <div className="flex items-center justify-between border-t border-border/70 bg-card/60 px-6 py-3">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setJsonText(JSON.stringify(DEFAULT_WORKFLOW_TEMPLATE, null, 2))}
            className="text-xs text-muted-foreground"
          >
            Reset to Template
          </Button>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" size="sm" className="gap-1.5" onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              <span>Save Workflow</span>
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

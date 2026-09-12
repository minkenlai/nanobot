import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Clock,
  Code,
  GitFork,
  History,
  Loader2,
  Play,
  Plus,
  RotateCcw,
  Trash2,
  Workflow,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useClient } from "@/providers/ClientProvider";
import type { WorkflowDefinition, WorkflowRunRecord } from "@/lib/types";
import {
  deleteWorkflow,
  fetchWorkflowRuns,
  fetchWorkflows,
} from "@/lib/api";
import { WorkflowCanvas } from "./WorkflowCanvas";
import { WorkflowEditorModal } from "./WorkflowEditorModal";
import { WorkflowInspector } from "./WorkflowInspector";
import { WorkflowRunHistory } from "./WorkflowRunHistory";
import { WorkflowRunModal } from "./WorkflowRunModal";

interface WorkflowsViewProps {
  onBackToChat?: () => void;
}

export function WorkflowsView({ onBackToChat }: WorkflowsViewProps) {
  const { client, token, getToken } = useClient();

  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Inspector & modal states
  const [selectedStateName, setSelectedStateName] = useState<string | null>(null);
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [selectedRun, setSelectedRun] = useState<WorkflowRunRecord | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [showRunsPanel, setShowRunsPanel] = useState(true);
  const [showEditorModal, setShowEditorModal] = useState(false);
  const [showRunModal, setShowRunModal] = useState(false);

  const activeToken = getToken ? getToken() || token : token;

  const loadWorkflows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchWorkflows(activeToken);
      const list = resp?.workflows || [];
      setWorkflows(list);
      if (list.length > 0) {
        setSelectedWorkflowId((prev) => (prev && list.some((w) => w.id === prev) ? prev : list[0].id));
      } else {
        setSelectedWorkflowId(null);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load workflows");
    } finally {
      setLoading(false);
    }
  }, [activeToken]);

  const loadRuns = useCallback(async (workflowId: string) => {
    setLoadingRuns(true);
    try {
      const resp = await fetchWorkflowRuns(activeToken, workflowId);
      setRuns(resp?.runs || []);
    } catch {
      setRuns([]);
    } finally {
      setLoadingRuns(false);
    }
  }, [activeToken]);

  useEffect(() => {
    loadWorkflows();
  }, [loadWorkflows]);

  useEffect(() => {
    if (selectedWorkflowId) {
      loadRuns(selectedWorkflowId);
      setSelectedRun(null);
      setSelectedStateName(null);
    } else {
      setRuns([]);
      setSelectedRun(null);
      setSelectedStateName(null);
    }
  }, [selectedWorkflowId, loadRuns]);

  const currentWorkflow = workflows.find((w) => w.id === selectedWorkflowId) || null;

  const handleDelete = async () => {
    if (!currentWorkflow) return;
    if (!confirm(`Are you sure you want to delete workflow "${currentWorkflow.name}" (${currentWorkflow.id})?`)) {
      return;
    }
    try {
      await deleteWorkflow(client, currentWorkflow.id);
      loadWorkflows();
    } catch (err: any) {
      alert(`Failed to delete workflow: ${err.message}`);
    }
  };

  return (
    <div className="flex h-full w-full flex-col bg-background text-foreground overflow-hidden">
      {/* Top Navigation Bar */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card/80 px-4 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          {onBackToChat && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onBackToChat}
              className="gap-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="h-4 w-4" />
              <span>Back</span>
            </Button>
          )}

          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <GitFork className="h-4 w-4" />
            </div>
            <span className="font-bold text-sm tracking-tight">Task Workflows</span>
          </div>

          {/* Workflow Selector */}
          {workflows.length > 0 && (
            <select
              value={selectedWorkflowId || ""}
              onChange={(e) => setSelectedWorkflowId(e.target.value)}
              className="ml-2 rounded-lg border border-border bg-card px-2.5 py-1 text-xs font-medium focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {workflows.map((wf) => (
                <option key={wf.id} value={wf.id}>
                  {wf.name} ({wf.id})
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {currentWorkflow && (
            <>
              {currentWorkflow.trigger?.cron && (
                <div className="hidden sm:flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2.5 py-1 text-[11px] text-muted-foreground">
                  <Clock className="h-3 w-3 text-primary" />
                  <span>{currentWorkflow.trigger.cron}</span>
                </div>
              )}

              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 gap-1.5 text-xs"
                onClick={() => setShowRunModal(true)}
              >
                <Play className="h-3.5 w-3.5 fill-current text-emerald-600 dark:text-emerald-400" />
                <span>Run</span>
              </Button>

              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 gap-1.5 text-xs"
                onClick={() => setShowEditorModal(true)}
              >
                <Code className="h-3.5 w-3.5" />
                <span>Edit JSON</span>
              </Button>

              <Button
                type="button"
                size="sm"
                variant={showRunsPanel ? "secondary" : "outline"}
                className="h-8 gap-1.5 text-xs"
                onClick={() => setShowRunsPanel((prev) => !prev)}
              >
                <History className="h-3.5 w-3.5" />
                <span>Runs ({runs.length})</span>
              </Button>

              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-8 w-8 p-0 text-muted-foreground hover:text-rose-600"
                onClick={handleDelete}
                title="Delete workflow"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </>
          )}

          <Button
            type="button"
            size="sm"
            className="h-8 gap-1.5 text-xs"
            onClick={() => {
              setSelectedWorkflowId(null);
              setShowEditorModal(true);
            }}
          >
            <Plus className="h-3.5 w-3.5" />
            <span>New Workflow</span>
          </Button>
        </div>
      </header>

      {/* Main Workspace Area */}
      <div className="relative flex flex-1 overflow-hidden">
        {loading ? (
          <div className="flex h-full w-full items-center justify-center gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading workflows...</span>
          </div>
        ) : error ? (
          <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="text-sm text-rose-500 font-mono">{error}</p>
            <Button size="sm" variant="outline" onClick={loadWorkflows}>
              <RotateCcw className="h-3.5 w-3.5 mr-1" /> Retry
            </Button>
          </div>
        ) : workflows.length === 0 ? (
          <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-8 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Workflow className="h-8 w-8" />
            </div>
            <div className="max-w-md space-y-1">
              <h2 className="text-base font-semibold">No Task Workflows Configured</h2>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Task workflows are declarative state machines chaining agent LLM turns, tool
                calls, notifications, and conditional choices. Create your first workflow or ask
                the agent to design one.
              </p>
            </div>
            <Button
              size="sm"
              className="gap-1.5"
              onClick={() => {
                setSelectedWorkflowId(null);
                setShowEditorModal(true);
              }}
            >
              <Plus className="h-4 w-4" /> Create Workflow
            </Button>
          </div>
        ) : currentWorkflow ? (
          <>
            {/* Visual React Flow Canvas */}
            <div className="flex-1 relative h-full">
              <WorkflowCanvas
                workflow={currentWorkflow}
                selectedRun={selectedRun}
                selectedStateName={selectedStateName}
                onSelectState={(name) => setSelectedStateName(name)}
              />
            </div>

            {/* Side Drawer: Selected State Inspector */}
            {selectedStateName && (
              <div className="w-80 md:w-96 shrink-0 h-full">
                <WorkflowInspector
                  stateName={selectedStateName}
                  workflow={currentWorkflow}
                  selectedRun={selectedRun}
                  onClose={() => setSelectedStateName(null)}
                />
              </div>
            )}

            {/* Side Drawer: Run History */}
            {showRunsPanel && !selectedStateName && (
              <div className="w-72 md:w-80 shrink-0 h-full">
                <WorkflowRunHistory
                  runs={runs}
                  selectedRunId={selectedRun?.run_id}
                  onSelectRun={(run) => setSelectedRun(run)}
                  onRefresh={() => currentWorkflow && loadRuns(currentWorkflow.id)}
                  loading={loadingRuns}
                />
              </div>
            )}
          </>
        ) : null}
      </div>

      {/* Editor Modal */}
      {showEditorModal && (
        <WorkflowEditorModal
          initialWorkflow={currentWorkflow}
          onClose={() => setShowEditorModal(false)}
          onSaveComplete={(saved) => {
            loadWorkflows();
            setSelectedWorkflowId(saved.id);
          }}
        />
      )}

      {/* Run Modal */}
      {showRunModal && currentWorkflow && (
        <WorkflowRunModal
          workflow={currentWorkflow}
          onClose={() => setShowRunModal(false)}
          onRunComplete={(record) => {
            setSelectedRun(record);
            if (currentWorkflow) {
              loadRuns(currentWorkflow.id);
            }
          }}
        />
      )}
    </div>
  );
}

import dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";
import { MarkerType } from "@xyflow/react";
import type {
  StepExecutionRecord,
  WorkflowChoiceState,
  WorkflowDefinition,
  WorkflowRunRecord,
  WorkflowState,
} from "@/lib/types";

export const NODE_WIDTH = 240;
export const NODE_HEIGHT = 100;

export interface WorkflowNodeData extends Record<string, unknown> {
  stateName: string;
  state: WorkflowState | { type: "start" };
  isStart?: boolean;
  stepRecord?: StepExecutionRecord;
  isSelected?: boolean;
  onSelectNode?: (name: string) => void;
}

export function buildWorkflowGraph(
  workflow: WorkflowDefinition,
  selectedRun?: WorkflowRunRecord | null,
  activeStateName?: string | null,
  direction: "TB" | "LR" = "TB",
): { nodes: Node<WorkflowNodeData>[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: direction, nodesep: 60, ranksep: 70 });
  g.setDefaultEdgeLabel(() => ({}));

  // Map run steps by state name for execution telemetry overlay
  const stepMap = new Map<string, StepExecutionRecord>();
  if (selectedRun && Array.isArray(selectedRun.steps)) {
    for (const step of selectedRun.steps) {
      stepMap.set(step.state_name, step);
    }
  }

  const rawNodes: Array<{ id: string; data: WorkflowNodeData }> = [];
  const rawEdges: Edge[] = [];

  // Start indicator node
  const startId = "__start__";
  g.setNode(startId, { width: 140, height: 48 });
  rawNodes.push({
    id: startId,
    data: {
      stateName: "START",
      state: { type: "start" },
      isStart: true,
    },
  });

  if (workflow.start_at && workflow.states[workflow.start_at]) {
    g.setEdge(startId, workflow.start_at);
    rawEdges.push({
      id: `${startId}->${workflow.start_at}`,
      source: startId,
      target: workflow.start_at,
      animated: true,
      style: { stroke: "#3b82f6", strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#3b82f6" },
    });
  }

  // Add all states
  for (const [name, state] of Object.entries(workflow.states)) {
    g.setNode(name, { width: NODE_WIDTH, height: NODE_HEIGHT });
    const stepRecord = stepMap.get(name);
    rawNodes.push({
      id: name,
      data: {
        stateName: name,
        state,
        isStart: name === workflow.start_at,
        stepRecord,
        isSelected: name === activeStateName,
      },
    });

    // Edges based on state type
    if (state.type === "choice") {
      const choiceState = state as WorkflowChoiceState;
      if (Array.isArray(choiceState.choices)) {
        choiceState.choices.forEach((choice, idx) => {
          if (choice.next && workflow.states[choice.next]) {
            const edgeId = `${name}->${choice.next}-${idx}`;
            const label = formatChoiceLabel(choice);
            g.setEdge(name, choice.next);
            rawEdges.push({
              id: edgeId,
              source: name,
              target: choice.next,
              label,
              style: { stroke: "#8b5cf6", strokeDasharray: "4 4" },
              markerEnd: { type: MarkerType.ArrowClosed, color: "#8b5cf6" },
            });
          }
        });
      }
      if (choiceState.default && workflow.states[choiceState.default]) {
        const edgeId = `${name}->${choiceState.default}-default`;
        g.setEdge(name, choiceState.default);
        rawEdges.push({
          id: edgeId,
          source: name,
          target: choiceState.default,
          label: "default",
          style: { stroke: "#6b7280" },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#6b7280" },
        });
      }
    } else if ("next" in state && state.next && workflow.states[state.next]) {
      const targetStateName = state.next;
      const edgeId = `${name}->${targetStateName}`;
      g.setEdge(name, targetStateName);
      rawEdges.push({
        id: edgeId,
        source: name,
        target: targetStateName,
        style: { stroke: "#64748b", strokeWidth: 1.8 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#64748b" },
      });
    }
  }

  // Compute auto-layout
  dagre.layout(g);

  // Position nodes
  const nodes: Node<WorkflowNodeData>[] = rawNodes.map((n) => {
    const nodeWithPos = g.node(n.id);
    const width = n.id === startId ? 140 : NODE_WIDTH;
    const height = n.id === startId ? 48 : NODE_HEIGHT;
    return {
      id: n.id,
      type: n.id === startId ? "startNode" : "workflowStateNode",
      position: {
        x: (nodeWithPos?.x ?? 0) - width / 2,
        y: (nodeWithPos?.y ?? 0) - height / 2,
      },
      data: n.data,
    };
  });

  return { nodes, edges: rawEdges };
}

function formatChoiceLabel(choice: { variable?: string; equals?: unknown; numeric_gt?: number; numeric_lt?: number; boolean_equals?: boolean }): string {
  const v = choice.variable ? choice.variable.replace(/^\$\./, "") : "?";
  if (choice.equals !== undefined) return `${v} == ${JSON.stringify(choice.equals)}`;
  if (choice.numeric_gt !== undefined) return `${v} > ${choice.numeric_gt}`;
  if (choice.numeric_lt !== undefined) return `${v} < ${choice.numeric_lt}`;
  if (choice.boolean_equals !== undefined) return `${v} is ${choice.boolean_equals}`;
  return v;
}

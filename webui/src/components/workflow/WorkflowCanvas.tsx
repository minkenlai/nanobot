import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowDownUp, ArrowLeftRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { WorkflowDefinition, WorkflowRunRecord } from "@/lib/types";
import {
  buildWorkflowGraph,
  type WorkflowNodeData,
} from "./workflow-layout";
import { StartNode, WorkflowStateNode } from "./WorkflowNodes";

interface WorkflowCanvasProps {
  workflow: WorkflowDefinition;
  selectedRun?: WorkflowRunRecord | null;
  selectedStateName?: string | null;
  onSelectState?: (name: string | null) => void;
}

const nodeTypes = {
  startNode: StartNode,
  workflowStateNode: WorkflowStateNode,
};

export function WorkflowCanvas({
  workflow,
  selectedRun,
  selectedStateName,
  onSelectState,
}: WorkflowCanvasProps) {
  const [direction, setDirection] = useState<"TB" | "LR">("TB");

  const { nodes: initialNodes, edges: initialEdges } = useMemo(() => {
    return buildWorkflowGraph(workflow, selectedRun, selectedStateName, direction);
  }, [workflow, selectedRun, selectedStateName, direction]);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<WorkflowNodeData>>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);

  // Sync graph whenever workflow, layout direction, or selected state changes
  useEffect(() => {
    const { nodes: newNodes, edges: newEdges } = buildWorkflowGraph(
      workflow,
      selectedRun,
      selectedStateName,
      direction,
    );
    setNodes(newNodes);
    setEdges(newEdges);
  }, [workflow, selectedRun, selectedStateName, direction, setNodes, setEdges]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      if (node.id === "__start__") {
        onSelectState?.(null);
      } else {
        onSelectState?.(node.id);
      }
    },
    [onSelectState],
  );

  const onPaneClick = useCallback(() => {
    onSelectState?.(null);
  }, [onSelectState]);

  return (
    <div className="relative h-full w-full bg-background/50 select-none">
      {/* Top toolbar */}
      <div className="absolute left-4 top-4 z-10 flex items-center gap-1.5 rounded-lg border border-border/80 bg-card/90 p-1 shadow-sm backdrop-blur-sm">
        <Button
          type="button"
          size="sm"
          variant={direction === "TB" ? "secondary" : "ghost"}
          className="h-7 gap-1 px-2 text-xs"
          onClick={() => setDirection("TB")}
          title="Vertical layout"
        >
          <ArrowDownUp className="h-3.5 w-3.5" />
          <span>Vertical</span>
        </Button>
        <Button
          type="button"
          size="sm"
          variant={direction === "LR" ? "secondary" : "ghost"}
          className="h-7 gap-1 px-2 text-xs"
          onClick={() => setDirection("LR")}
          title="Horizontal layout"
        >
          <ArrowLeftRight className="h-3.5 w-3.5" />
          <span>Horizontal</span>
        </Button>
      </div>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={1.5}
        className="touch-none"
      >
        <Background gap={16} size={1} />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap
          nodeStrokeWidth={3}
          zoomable
          pannable
          position="bottom-right"
          className="!bg-card/80 !border-border !rounded-lg overflow-hidden shadow-sm"
        />
      </ReactFlow>
    </div>
  );
}

"use client";

import { useState } from "react";
import type { PlanTree } from "@/lib/api/types";
import { ancestorIds, expandableIds } from "@/lib/plan/analysis";

export interface PlanCollapse {
  collapsed: ReadonlySet<number>;
  toggle: (id: number, expand: boolean) => void;
  expandAll: () => void;
  collapseAll: () => void;
}

/** Collapsed rows of a plan tree. A node selected from elsewhere (evidence, report, Jump to
 * hottest) is revealed: its collapsed ancestors expand when the selection changes. */
export function usePlanCollapse(plan: PlanTree, selectedId: number | null | undefined): PlanCollapse {
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set());
  const [revealed, setRevealed] = useState<number | null | undefined>(undefined);
  // Adjusting state while rendering when a prop changes (React docs pattern), not in an effect.
  if (selectedId !== revealed) {
    setRevealed(selectedId);
    if (selectedId != null) {
      const up = ancestorIds(plan, selectedId);
      if (up.some((id) => collapsed.has(id))) setCollapsed(new Set([...collapsed].filter((id) => !up.includes(id))));
    }
  }
  return {
    collapsed,
    toggle: (id, expand) =>
      setCollapsed((prev) => {
        const next = new Set(prev);
        if (expand) next.delete(id);
        else next.add(id);
        return next;
      }),
    expandAll: () => setCollapsed(new Set()),
    collapseAll: () => setCollapsed(new Set(expandableIds(plan))),
  };
}

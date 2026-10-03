import { useState } from "react";
import { Checkbox, Text } from "@fluentui/react-components";

/**
 * A lightweight, client-only guided walkthrough for a Monolith-to-modular
 * plan's own `deployment_plan` rollout steps - deliberately NOT another
 * real-infrastructure flow like ModernizationDeploymentPanel: the plan's
 * proposed_components graph and rewrite_strategy already deliver the
 * "how to modularize" content; this just helps the user track progress
 * through the rollout steps Genie already proposed, locally in the
 * browser (no backend persistence - re-opening this plan starts unchecked).
 */
export function ModernizationWalkthrough({ steps }: { steps: string[] }): JSX.Element | null {
  const [checked, setChecked] = useState<boolean[]>(() => steps.map(() => false));

  if (steps.length === 0) return null;

  const completedCount = checked.filter(Boolean).length;

  return (
    <div className="modernization-walkthrough">
      <Text weight="semibold">
        What's next: walk through this modularization ({completedCount}/{steps.length})
      </Text>
      <Text size={200} style={{ display: "block", opacity: 0.72 }}>
        Track your own progress through the rollout steps Genie already proposed above - this is
        just a local checklist, not another approval or deployment.
      </Text>
      <ul className="modernization-walkthrough-list">
        {steps.map((step, index) => (
          <li key={index}>
            <Checkbox
              label={step}
              checked={checked[index]}
              onChange={(_, data) =>
                setChecked((current) =>
                  current.map((value, itemIndex) => (itemIndex === index ? Boolean(data.checked) : value)),
                )
              }
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

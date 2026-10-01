import { Button, Text } from "@fluentui/react-components";
import { useNavigate } from "react-router-dom";
import { PageHeader } from "@/layouts/AppShell";

/**
 * Consistent empty state for every mission-flow step that needs an active
 * workflow run (Architecture, UI & Agent Design, Governance, Deploy &
 * Launch) and currently has none - e.g. the user jumped straight to this
 * step from Home before starting any mission. Always offers a real way
 * back to Home instead of only prose mentioning "Upload", which stopped
 * being the only way to start a mission once Home gained multiple
 * capability-specific entry points.
 */
export function NoActiveMissionState({
  title,
  message = "Start a mission from Home to see this step's results here.",
}: {
  title: string;
  message?: string;
}): JSX.Element {
  const navigate = useNavigate();
  return (
    <div>
      <PageHeader title={title} subtitle="No active mission yet." />
      <Text size={300} style={{ opacity: 0.7, display: "block", marginBottom: 12 }}>
        {message}
      </Text>
      <Button appearance="primary" onClick={() => navigate("/")}>
        Go to Home
      </Button>
    </div>
  );
}

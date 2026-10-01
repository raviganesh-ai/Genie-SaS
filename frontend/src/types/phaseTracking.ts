export type PhaseTaskStatus = "pending" | "in_progress" | "blocked" | "completed";

export interface PhaseTaskState {
  id: string;
  session_id: string;
  phase_id: string;
  task_id: string;
  status: PhaseTaskStatus;
  evidence_uri: string | null;
  evidence_provider: "azure" | "github" | "genie" | null;
  evidence_verified_at: string | null;
  evidence_reference: string | null;
  detail: string;
  updated_by: string;
  updated_at: string;
}

export interface TrackedTask {
  definition: { id: string; name: string };
  state: PhaseTaskState;
}

export interface TrackedPhase {
  id: string;
  name: string;
  tasks: TrackedTask[];
}

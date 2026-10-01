import { apiFetch, downloadBinary } from "./httpClient";
import type { DeploymentPipelineRun } from "@/types/deployLaunch";
import type { ApprovalRequest } from "@/types/governance";

export const deployLaunchApi = {
  /**
   * Starts or re-attempts the real Deploy & Launch pipeline.
   *
   * If `resumeFromStep` is provided, the pipeline resumes from that step instead
   * of starting from the first step, allowing retry from a failed step without
   * re-running prior completed steps.
   */
  start(
    sessionId: string,
    workflowRunId: string,
    traceId?: string,
    resumeFromStep?: string,
    approvalRequestId?: string,
  ): Promise<DeploymentPipelineRun> {
    return apiFetch<DeploymentPipelineRun>(`/sessions/${sessionId}/deploy-launch/start`, {
      method: "POST",
      body: {
        workflow_run_id: workflowRunId,
        trace_id: traceId ?? null,
        resume_from_step: resumeFromStep ?? null,
        approval_request_id: approvalRequestId ?? null,
      },
    });
  },
  requestApproval(
    sessionId: string,
    workflowRunId: string,
    traceId?: string,
  ): Promise<ApprovalRequest> {
    return apiFetch<ApprovalRequest>(
      `/sessions/${sessionId}/deploy-launch/request-approval`,
      {
        method: "POST",
        body: { workflow_run_id: workflowRunId, trace_id: traceId ?? null },
      },
    );
  },
  list(sessionId: string): Promise<DeploymentPipelineRun[]> {
    return apiFetch<DeploymentPipelineRun[]>(`/sessions/${sessionId}/deploy-launch/`);
  },
  get(sessionId: string, pipelineRunId: string): Promise<DeploymentPipelineRun> {
    return apiFetch<DeploymentPipelineRun>(`/sessions/${sessionId}/deploy-launch/${pipelineRunId}`);
  },
  /** Downloads a zip of the materialized backend build plus the generated least-access policy document. */
  async download(sessionId: string, pipelineRunId: string): Promise<{ blob: Blob; filename: string }> {
    return downloadBinary(`/sessions/${sessionId}/deploy-launch/${pipelineRunId}/download`);
  },
};

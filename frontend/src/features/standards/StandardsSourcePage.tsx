import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Dropdown,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Spinner,
  Text,
  Title2,
} from "@fluentui/react-components";
import { ErrorState } from "@/components/ErrorState";
import { ApiError } from "@/services/httpClient";
import { repositoryConnectionApi } from "@/services/repositoryConnectionApi";
import { standardsApi } from "@/services/standardsApi";
import { useSessionContext } from "@/state/SessionContext";
import type { SafeError } from "@/types/common";
import type { RepositoryAssessment, RepositoryPurposeBinding } from "@/types/repositoryConnection";
import type { StandardsConformanceReport, StandardsSnapshot } from "@/types/standards";

export function StandardsSourcePage(): JSX.Element {
  const navigate = useNavigate();
  const { sessionId } = useSessionContext();
  const [bindings, setBindings] = useState<RepositoryPurposeBinding[]>([]);
  const [assessments, setAssessments] = useState<RepositoryAssessment[]>([]);
  const [snapshot, setSnapshot] = useState<StandardsSnapshot | null>(null);
  const [report, setReport] = useState<StandardsConformanceReport | null>(null);
  const [bindingId, setBindingId] = useState("");
  const [assessmentId, setAssessmentId] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const [allBindings, allAssessments, snapshots] = await Promise.all([
        repositoryConnectionApi.listBindings(sessionId),
        repositoryConnectionApi.listAssessments(sessionId),
        standardsApi.list(sessionId),
      ]);
      const standardsBindings = allBindings.filter(
        (binding) => binding.purpose === "standards" && binding.status === "approved",
      );
      setBindings(standardsBindings);
      setAssessments(allAssessments);
      setBindingId((current) => current || standardsBindings[0]?.id || "");
      setAssessmentId((current) => current || allAssessments[0]?.id || "");
      setSnapshot(snapshots[0] ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Unable to load standards evidence." });
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const ruleById = useMemo(
    () => new Map(snapshot?.rules.map((rule) => [rule.id, rule]) ?? []),
    [snapshot],
  );

  const ingest = useCallback(async () => {
    if (!sessionId || !bindingId) return;
    setWorking(true);
    setError(null);
    setReport(null);
    try {
      setSnapshot(await standardsApi.ingest(sessionId, bindingId));
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Standards ingestion failed." });
    } finally {
      setWorking(false);
    }
  }, [sessionId, bindingId]);

  const evaluate = useCallback(async () => {
    if (!sessionId || !snapshot || !assessmentId) return;
    setWorking(true);
    setError(null);
    try {
      setReport(await standardsApi.evaluate(sessionId, snapshot.id, assessmentId));
    } catch (err) {
      setError(err instanceof ApiError ? err : { message: "Standards evaluation failed." });
    } finally {
      setWorking(false);
    }
  }, [sessionId, snapshot, assessmentId]);

  if (!sessionId) {
    return <ErrorState error={{ message: "Create a session before ingesting standards." }} />;
  }

  return (
    <section className="genie-fade-in repository-intake">
      <div>
        <Title2>Architecture Standards Source</Title2>
        <Text block style={{ opacity: 0.72, marginTop: 6 }}>
          Ingest approved Markdown from the Standards repository at its immutable commit, retain
          line-level citations, and evaluate dependency graph conformance.
        </Text>
      </div>
      <Card className="repository-intake-card">
        <Text weight="semibold">Commit-pinned standards</Text>
        {loading ? <Spinner label="Loading standards bindings..." /> : null}
        <Dropdown
          placeholder="Select the approved Standards repository"
          value={bindings.find((binding) => binding.id === bindingId)?.repository_full_name ?? ""}
          selectedOptions={bindingId ? [bindingId] : []}
          disabled={loading || working}
          onOptionSelect={(_, data) => setBindingId(data.optionValue ?? "")}
        >
          {bindings.map((binding) => (
            <Option key={binding.id} value={binding.id} text={binding.repository_full_name}>
              {binding.repository_full_name}
            </Option>
          ))}
        </Dropdown>
        <Button appearance="primary" disabled={!bindingId || working} onClick={() => void ingest()}>
          {working ? "Reading standards..." : "Ingest live standards snapshot"}
        </Button>
      </Card>

      {snapshot ? (
        <>
          <Card className="repository-intake-card">
            <div className="dependency-mapping-heading">
              <div>
                <Text weight="semibold">{snapshot.repository_full_name}</Text>
                <Text block size={200} className="repository-commit">{snapshot.commit}</Text>
              </div>
              <Badge color="success">{snapshot.rules.length} cited rules</Badge>
            </div>
            {snapshot.conflicts.map((conflict, index) => (
              <MessageBar intent="error" key={index}>
                <MessageBarBody>
                  <MessageBarTitle>Standards conflict</MessageBarTitle>
                  {conflict.detail}
                </MessageBarBody>
              </MessageBar>
            ))}
            {snapshot.gaps.map((gap) => (
              <MessageBar intent="warning" key={gap}>
                <MessageBarBody>{gap}</MessageBarBody>
              </MessageBar>
            ))}
            <div className="standards-rule-list">
              {snapshot.rules.map((rule) => (
                <div className="standards-rule" key={rule.id}>
                  <Badge>{rule.classification}</Badge>
                  <div>
                    <Text>{rule.statement}</Text>
                    <Text block size={200} style={{ opacity: 0.65 }}>
                      {rule.citation.path}:{rule.citation.line}
                    </Text>
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <Card className="repository-intake-card">
            <Text weight="semibold">Evaluate repository conformance</Text>
            <Dropdown
              placeholder="Select a completed dependency assessment"
              value={
                assessments.find((assessment) => assessment.id === assessmentId)
                  ?.repository_full_name ?? ""
              }
              selectedOptions={assessmentId ? [assessmentId] : []}
              onOptionSelect={(_, data) => setAssessmentId(data.optionValue ?? "")}
            >
              {assessments.map((assessment) => (
                <Option
                  key={assessment.id}
                  value={assessment.id}
                  text={assessment.repository_full_name}
                >
                  {assessment.repository_full_name}
                </Option>
              ))}
            </Dropdown>
            <Button
              appearance="primary"
              disabled={!assessmentId || working}
              onClick={() => void evaluate()}
            >
              Evaluate cited standards
            </Button>
            {report?.results.map((result) => (
              <div className="standards-rule" key={result.rule_id}>
                <Badge
                  color={
                    result.status === "conformant"
                      ? "success"
                      : result.status === "non_conformant"
                        ? "danger"
                        : "warning"
                  }
                >
                  {result.status}
                </Badge>
                <div>
                  <Text>{ruleById.get(result.rule_id)?.statement ?? result.rule_id}</Text>
                  <Text block size={200} style={{ opacity: 0.65 }}>{result.detail}</Text>
                </div>
              </div>
            ))}
          </Card>
          <Button appearance="secondary" onClick={() => navigate("/iq-collaboration")}>
            Continue to IQ Collaboration
          </Button>
        </>
      ) : null}
      {error ? <ErrorState error={error} onRetry={() => void load()} /> : null}
    </section>
  );
}

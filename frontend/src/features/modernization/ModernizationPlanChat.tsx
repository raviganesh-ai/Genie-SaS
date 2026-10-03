import { useCallback, useState } from "react";
import { Badge, Button, Input, Spinner, Text } from "@fluentui/react-components";
import { ErrorState } from "@/components/ErrorState";
import { ApiError } from "@/services/httpClient";
import { modernizationApi } from "@/services/modernizationApi";
import type { SafeError } from "@/types/common";

interface ChatMessage {
  id: string;
  role: "user" | "genie";
  text: string;
  referencedFields?: string[];
}

/**
 * A conversational panel attached to one modernization plan - lets the
 * user ask grounded questions about it ("Ask Genie") and, separately,
 * submit free-text feedback to regenerate a new, independently
 * approvable plan that incorporates it ("Refine this plan"). The same
 * draft text feeds either action; "Ask Genie" never changes the plan,
 * "Refine this plan" always produces an additional plan rather than
 * editing this one in place (see ModernizationPage.refine).
 */
export function ModernizationPlanChat({
  sessionId,
  planId,
  onRefine,
  refining,
}: {
  sessionId: string;
  planId: string;
  onRefine: (refinementNotes: string) => void;
  refining: boolean;
}): JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<SafeError | null>(null);

  const ask = useCallback(async () => {
    const message = draft.trim();
    if (!message || asking) return;
    setMessages((current) => [...current, { id: `${Date.now()}-user`, role: "user", text: message }]);
    setDraft("");
    setError(null);
    setAsking(true);
    try {
      const result = await modernizationApi.ask(sessionId, planId, message);
      setMessages((current) => [
        ...current,
        {
          id: `${Date.now()}-genie`,
          role: "genie",
          text: result.answer,
          referencedFields: result.referenced_fields,
        },
      ]);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : { message: "Unable to answer that question." });
    } finally {
      setAsking(false);
    }
  }, [sessionId, planId, draft, asking]);

  const refine = useCallback(() => {
    const notes = draft.trim();
    if (!notes || refining) return;
    setDraft("");
    onRefine(notes);
  }, [draft, refining, onRefine]);

  return (
    <div className="modernization-chat">
      <Text weight="semibold">Ask or refine this plan</Text>
      <Text size={200} style={{ display: "block", opacity: 0.72 }}>
        Ask anything about this plan, or describe a change (e.g. "keep notifications inside the
        monolith" or "target Container Apps instead") and use Refine to regenerate it with that
        feedback - Genie never edits this plan in place.
      </Text>
      {messages.length > 0 ? (
        <ul className="dependency-chat-log">
          {messages.map((item) => (
            <li key={item.id} className={`dependency-chat-message dependency-chat-message-${item.role}`}>
              <Text size={200} weight="semibold">{item.role === "user" ? "You" : "Genie"}</Text>
              <Text size={200}>{item.text}</Text>
              {item.role === "genie" && item.referencedFields && item.referencedFields.length > 0 ? (
                <div className="dependency-chat-references">
                  {item.referencedFields.map((field) => (
                    <Badge key={field} appearance="outline" size="small">{field}</Badge>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <ErrorState error={error} /> : null}
      <div className="dependency-chat-row">
        <Input
          className="dependency-chat-input"
          placeholder="e.g. Why was the notifications service extracted?"
          value={draft}
          disabled={asking || refining}
          onChange={(_, data) => setDraft(data.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void ask();
            }
          }}
        />
        <Button appearance="primary" disabled={asking || refining || !draft.trim()} onClick={() => void ask()}>
          {asking ? "Asking..." : "Ask Genie"}
        </Button>
        <Button appearance="secondary" disabled={asking || refining || !draft.trim()} onClick={refine}>
          {refining ? "Refining..." : "Refine this plan"}
        </Button>
      </div>
      {asking ? <Spinner size="tiny" label="Genie is reading this plan..." /> : null}
    </div>
  );
}

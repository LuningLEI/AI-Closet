"use client";

import { useState } from "react";
import AuthGate from "../../components/AuthGate";
import { ChatRequest, ChatResponse } from "../../types";
import { apiClient } from "../../lib/api-client";

const starterPrompts = [
  "Summarize my closet and tell me what categories are missing.",
  "Recommend an outfit for a 58F work day.",
  "Explain how the agent skill system is using my wardrobe data.",
];

export default function ChatPage() {
  const [question, setQuestion] = useState(starterPrompts[1]);
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload: ChatRequest = { message: question };
      const result = await apiClient.chat.send(payload);
      setResponse(result);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Chat request failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthGate>
      <section className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Agent Chat</p>
          <h1>Skill-routed wardrobe assistant</h1>
          <p className="lead compact">
            The chat layer is intentionally wired through explicit skills so you can show planning, tool boundaries,
            and structured outputs instead of a single opaque completion call.
          </p>
        </div>
      </header>

      <div className="dashboard-grid chat-layout">
        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="section-label">Prompt</p>
              <h2>Ask the wardrobe agent</h2>
            </div>
          </div>
          <div className="prompt-list">
            {starterPrompts.map((prompt) => (
              <button key={prompt} className="filter-chip" onClick={() => setQuestion(prompt)} type="button">
                {prompt}
              </button>
            ))}
          </div>

          <form className="chat-form" onSubmit={handleSubmit}>
            <label htmlFor="question">Question</label>
            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={6}
              placeholder="Recommend an outfit for a rainy day"
            />
            <button className="button primary" type="submit" disabled={busy || question.trim().length === 0}>
              {busy ? "Thinking..." : "Run Agent"}
            </button>
          </form>
          {error && <p className="status-error">{error}</p>}
        </section>

        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="section-label">Agent Output</p>
              <h2>Reply and tool trace</h2>
            </div>
          </div>

          {!response && <p className="status-muted">Run a prompt to inspect the reply and which skills were invoked.</p>}
          {response && (
            <div className="chat-result">
              <div className="chat-response">
                <h3>Reply</h3>
                <p>{response.reply}</p>
              </div>
              <div className="skill-list">
                {(response.skills_used ?? []).map((skill) => (
                  <article key={skill.name} className="skill-card">
                    <div className="skill-card-header">
                      <strong>{skill.name}</strong>
                      <span className="pill subtle">skill</span>
                    </div>
                    <pre>{JSON.stringify(skill.output, null, 2)}</pre>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
      </section>
    </AuthGate>
  );
}

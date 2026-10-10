import { useRef, useState, type FormEvent } from "react";
import { Bot, Eye, EyeOff, Info, Send, Sparkles, UserRound } from "lucide-react";
import { api, ApiError } from "../api";
import type { ChatMessage, Currency, Dashboard } from "../types";
import { amount } from "../format";

const suggestedQuestions = [
  "What does my available cash include?",
  "Explain my current investment mix.",
  "How would a €1,000 contribution be split?",
];

export function AssistantView({ data, currency }: { data: Dashboard; currency: Currency }) {
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  async function ask(nextQuestion: string) {
    if (!apiKey.trim()) {
      setError("Enter your OpenAI API key before asking a question.");
      return;
    }
    const normalized = nextQuestion.trim();
    if (!normalized || waiting) return;
    const history = messages.slice(-8);
    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: normalized }];
    setMessages(nextMessages);
    setQuestion("");
    setError("");
    setWaiting(true);
    try {
      const reply = await api.askAssistant(normalized, history, apiKey.trim());
      setMessages([...nextMessages, { role: "assistant", content: reply.answer }]);
      window.requestAnimationFrame(() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" }));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The assistant request could not be completed.");
    } finally {
      setWaiting(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await ask(question);
  }

  return (
    <div className="page-content assistant-page">
      <div className="page-intro compact-intro">
        <div>
          <div className="eyebrow">Read-only · grounded in your tracker</div>
          <h1>Ask with context.</h1>
          <p>Explore your numbers and goals in plain language—without letting a model change your plan.</p>
        </div>
        <div className="assistant-provider-pill"><span /> OpenAI-compatible · BYOK</div>
      </div>

      <div className="assistant-layout">
        <section className="panel chat-panel">
          <div className="chat-heading">
            <span className="assistant-avatar"><Bot size={20} /></span>
            <div><strong>Northstar assistant</strong><small>Answers use the current app snapshot.</small></div>
            <span className="chat-readonly">READ ONLY</span>
          </div>
          <div className="chat-messages" ref={listRef} aria-live="polite">
            {messages.length === 0 && (
              <div className="chat-welcome">
                <span className="welcome-sparkle"><Sparkles size={20} /></span>
                <h2>A second perspective, not a black box.</h2>
                <p>Ask about the current snapshot or try a question below. The assistant can explain recorded calculations, but it can’t execute transactions.</p>
                <div className="suggested-questions">
                  {suggestedQuestions.map((item) => (
                    <button key={item} type="button" onClick={() => void ask(item)}>{item}<span>↗</span></button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((message, index) => (
              <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
                <span className="message-avatar">{message.role === "assistant" ? <Bot size={15} /> : <UserRound size={15} />}</span>
                <div className="message-content">
                  <span className="message-author">{message.role === "assistant" ? "Northstar" : "You"}</span>
                  <p>{message.content}</p>
                </div>
              </div>
            ))}
            {waiting && (
              <div className="chat-message assistant">
                <span className="message-avatar"><Bot size={15} /></span>
                <div className="message-content"><span className="message-author">Northstar</span><p className="typing-indicator"><i /><i /><i /></p></div>
              </div>
            )}
          </div>
          <form className="chat-composer" onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="assistant-question">Ask a question</label>
            <textarea
              id="assistant-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask about your goals, cash flow, or allocation…"
              rows={2}
              maxLength={2000}
              disabled={waiting}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div className="composer-footer">
              <span>Use Shift + Enter for a new line</span>
              <button className="send-button" type="submit" disabled={waiting || !question.trim()} aria-label="Send question"><Send size={16} /></button>
            </div>
          </form>
          {error && <div className="chat-error" role="alert">{error}</div>}
          <div className="chat-disclaimer"><Info size={14} /> AI responses can be wrong. Check figures and assumptions in the tracker.</div>
        </section>

        <aside className="assistant-sidebar">
          <section className="panel api-key-panel">
            <div className="eyebrow">Your model access</div>
            <h2>Bring your own key.</h2>
            <p>Enter an OpenAI API key for this browser session. The app does not save it.</p>
            <label className="form-field api-key-field">
              <span>OpenAI API key</span>
              <div className="key-input-wrap">
                <input
                  autoComplete="off"
                  type={showKey ? "text" : "password"}
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder="sk-…"
                  spellCheck={false}
                />
                <button type="button" className="icon-button small" aria-label={showKey ? "Hide API key" : "Show API key"} onClick={() => setShowKey((value) => !value)}>
                  {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
            <div className="provider-note"><span className="secure-dot" /> Key is held in memory and sent only when you submit a question.</div>
          </section>

          <section className="panel context-panel">
            <div className="context-heading"><span className="context-icon"><Sparkles size={16} /></span><div><div className="eyebrow">Included app context</div><strong>What the assistant can see</strong></div></div>
            <ul>
              <li>Tracked totals and selected currency</li>
              <li>Asset-class targets and current mix</li>
              <li>Goal names, deadlines, and progress</li>
              <li>Current data-quality warnings</li>
            </ul>
            <div className="context-value">Portfolio snapshot: <strong>{amount(data.totals.net_worth, currency)}</strong></div>
          </section>

          <section className="assistant-privacy">
            <Info size={16} />
            <p>Your question and the listed aggregate context are sent to OpenAI. Conversation and key are not stored by this prototype. This is not zero-knowledge processing.</p>
          </section>
        </aside>
      </div>
    </div>
  );
}

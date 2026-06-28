import Anthropic from "@anthropic-ai/sdk";

// OPTIONAL on-demand narration (BUILD_PLAN §9). The pipeline needs 0 LLM calls;
// this only rewrites the existing deterministic `reason` into a natural sentence
// for a non-technical biller. Project-mandated model: Anthropic Haiku 4.5.
const MODEL = "claude-haiku-4-5";

export interface SummarizeInput {
  routing_decision: string | null;
  reason: string | null;
  score: number | null;
}

export async function summarizeTriage(row: SummarizeInput): Promise<string> {
  const client = new Anthropic(); // reads ANTHROPIC_API_KEY from the environment
  const msg = await client.messages.create({
    model: MODEL,
    max_tokens: 300,
    system:
      "You turn a structured wound-care billing triage decision into one or two " +
      "clear, natural sentences for a non-technical medical biller. Use ONLY the " +
      "facts provided — never invent clinical details, codes, or measurements, and " +
      "never give clinical advice. Be concise and plain-spoken.",
    messages: [
      {
        role: "user",
        content:
          `Routing decision: ${row.routing_decision ?? "unknown"}\n` +
          `Deterministic reason: ${row.reason ?? "(none)"}\n` +
          `Score: ${row.score ?? "n/a"}\n\n` +
          "Write a 1–2 sentence summary for the biller explaining what to do and why.",
      },
    ],
  });
  return msg.content
    .filter((b): b is Anthropic.TextBlock => b.type === "text")
    .map((b) => b.text)
    .join("")
    .trim();
}

import { describe, expect, it } from "vitest";

import { consumeSseStream } from "./sse";

function streamFromChunks(chunks: string[]) {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe("consumeSseStream", () => {
  it("parses split SSE data events", async () => {
    const events: unknown[] = [];
    await consumeSseStream(
      streamFromChunks([
        'data: {"type":"assistant_text_delta","text":"你',
        '好"}\n\n',
        'data: {"type":"status","message":"完成"}',
      ]),
      (event) => events.push(event),
    );

    expect(events).toEqual([
      { type: "assistant_text_delta", text: "你好" },
      { type: "status", message: "完成" },
    ]);
  });
});

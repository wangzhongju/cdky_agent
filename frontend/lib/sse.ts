export async function consumeSseStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (payload: unknown) => void,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (!line.startsWith("data: ")) {
          continue;
        }
        onEvent(JSON.parse(line.slice(6)));
      }
    }
  }

  const tail = buffer.trim();
  if (tail.startsWith("data: ")) {
    onEvent(JSON.parse(tail.slice(6)));
  }
}

# Gemini API

Equip your agent with current SDK patterns, model identifiers, and live
documentation lookup for building applications with the
[Gemini API](https://aistudio.google.com/docs).

## What's included

### Skills

| Skill | Description |
| :--- | :--- |
| `gemini-api-dev` | Build applications with the [Interactions API](https://aistudio.google.com/docs/interactions). Covers text generation, stateful multi-turn chat, streaming, function calling, structured output, image generation, speech generation (TTS), Voice Design, Voice Replication, managed agents, Deep Research, and migrations from `generateContent`. |
| `gemini-live-api-dev` | Build low-latency, bidirectional voice and video applications over WebSockets with the [Gemini Live API](https://aistudio.google.com/docs/live). Covers real-time audio/video streaming, background reasoning (extended thinking), asynchronous non-blocking tool calls, real-time transcription, live speech translation, and session management. |
| `gemini-omni-flash-api` | Generate and edit videos with Gemini Omni Flash using the Interactions API, including text-to-video, first-and-last-frame transitions, reference-guided generation, and video extensions. |

### MCP server

- **`gemini-api-docs`** (`https://gemini-api-docs-mcp.dev`): Provides
  `gemini_search_docs` and `gemini_get_doc` so your agent can search and read
  official Gemini API documentation directly without manual URL fetching.

## Prerequisites

1. **API key**: Set the `GEMINI_API_KEY` environment variable with a key from
   [Google AI Studio](https://aistudio.google.com/apikey).
2. **SDK installation**:
   - **Python**: `pip install -U google-genai`
   - **JavaScript / TypeScript**: `npm install @google/genai`

## Example prompts

- *"Build a stateful multi-turn chat script using the Interactions API and the
  latest models."*
- *"Create a real-time voice agent using the Gemini Live API and non-blocking
  function calling."*
- *"Generate multi-speaker dialogue audio using the latest Gemini TTS models
  and `speech_metadata` annotations."*
- *"Migrate `src/` from `client.models.generate_content` to
  `client.interactions.create`."*

## Resources

- [Gemini API Documentation in Google AI Studio](https://aistudio.google.com/docs)
- [Interactions API Guide](https://aistudio.google.com/docs/interactions)
- [GitHub Repository (`google-gemini/gemini-skills`)](https://github.com/google-gemini/gemini-skills)

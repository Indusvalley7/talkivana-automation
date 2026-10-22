# Fixed Talkivana Voice Library

The final whole-conversation section assigns one stable Chatterbox reference voice to each
character. Configure the approved files in `config/channel.json` under
`models.tts_settings.conversation_voice_references`.

Approved initial mapping:

- Speaker A: the current Chatterbox voice retained from the first Talkivana review sample
- Speaker B: the user-selected woman voice generated with the official Chatterbox V3 demo

Each reference must be a clean, licensed or owner-consented WAV clip with no music or effects.
Do not use celebrity audio, scraped speech, or a real person's voice without explicit consent.
Reference clips are selected once, reviewed once, and then held fixed so the characters remain
consistent over the life of the channel.

If a lesson contains more unique speakers than configured reference files, rendering must stop.
Add and approve another fixed synthetic reference before that lesson can proceed. The system must
never silently reuse a character voice or fall back to a different speech service.

See `VOICE_MANIFEST.json` for the immutable file hashes, technical properties, and provenance.

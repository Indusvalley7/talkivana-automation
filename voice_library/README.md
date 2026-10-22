# Fixed Talkivana Voice Library

The final whole-conversation section assigns one stable Chatterbox reference voice to each
character. Configure the approved files in `config/channel.json` under
`models.tts_settings.conversation_voice_references`.

Initial mapping:

- Speaker A: approved female-presenting synthetic reference
- Speaker B: approved male-presenting synthetic reference

Each reference must be a clean, licensed or owner-consented WAV clip with no music or effects.
Do not use celebrity audio, scraped speech, or a real person's voice without explicit consent.
Reference clips are selected once, reviewed once, and then held fixed so the characters remain
consistent over the life of the channel.

If a lesson contains more unique speakers than configured reference files, rendering must stop.
Add and approve another fixed synthetic reference before that lesson can proceed. The system must
never silently reuse a character voice or fall back to a different speech service.

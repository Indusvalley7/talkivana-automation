# Binding System Guardrails

1. Unattended scheduling is allowed only when deterministic content, uniqueness, rendering,
   manifest, thumbnail, and technical-QA gates all pass.
2. Recheck the Excel tracker and all current pack Issues immediately before production; materially
   repeated topics or confusingly similar titles must fail closed.
3. Upload completed files privately first. Schedule only those exact QA-verified private files.
4. Manual recovery commands remain restricted to the configured GitHub owner. Never treat silence,
   casual agreement, emoji, edited Issue text, or `APPROVE` as a repair command.
5. Fail closed on missing credentials, invalid language data, rendering errors, or incomplete upload manifests.
6. Never expose credentials, tokens, private recordings, generated narration, or full rendered
   files in Issues or Git history. Only user-approved synthetic reference clips with documented
   provenance may be versioned in the public repository.
7. Production narration uses only the pinned Chatterbox Multilingual voice configuration. Never
   substitute another voice automatically; stop and send a failure email if synthesis fails.
8. Never use scraped media, copyrighted characters, song lyrics, celebrity likenesses, or unlicensed assets.
9. Enforce two Shorts and two five-minute lessons per pack, with one-day vocabulary lead time.
10. Enforce seven unfinished packs across all open production states and stop generation at the cap.
11. Keep four publishing slots distinct and separated by at least three hours.
12. The timing agent cannot bypass QA, change content, or make videos public.
13. Rejected private preview deletion follows the approved 14-day retention rule.
14. Production remains disabled until setup, tests, preflight, and dry-run verification succeed.
15. Review copies must contain intelligible spoken narration; synthetic test tones are forbidden outside automated tests.
16. Teaching scenes show English above German. Each line uses English once and German twice. The simplified pronunciation guide remains visible but is never narrated. The final coherent conversation is German-only and is spoken once.
17. Use one approved rich-colour template consistently within each video and rotate templates across the four daily videos.
18. Tutor narration must sound bright, cheerful, encouraging, and conversational—not flat, sleepy, theatrical, or robotic.
19. Guided lessons include short tutor cues, visible pronunciation coaching, and encouragement; no silent sentence-practice gap may exceed six seconds.
20. In the final whole conversation, every character has one fixed approved voice. Different characters must not share a voice, and the same character must keep the same voice across lessons.
21. Standard German teaching narration uses the approved German reference recording. A voice retry must not silently fall back to the model's unprompted default voice.
22. Send email only for a failed monitored workflow. Never send routine success or approval mail.
23. Do not enable unattended production until the failure-email secrets and activation variable are configured.

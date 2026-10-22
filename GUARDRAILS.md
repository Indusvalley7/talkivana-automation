# Binding System Guardrails

1. Never schedule or publish without valid content approval followed by valid final-video approval.
2. Only the configured GitHub owner can issue commands.
3. Never treat silence, casual agreement, emoji, edited Issue text, or `APPROVE` as authorization.
4. Upload completed review copies privately. Final approval schedules those exact uploaded files.
5. Fail closed on missing credentials, invalid language data, rendering errors, or incomplete upload manifests.
6. Never expose credentials, tokens, private recordings, generated narration, or full rendered
   files in Issues or Git history. Only user-approved synthetic reference clips with documented
   provenance may be versioned in the public repository.
7. Production narration uses only the pinned Chatterbox Multilingual voice configuration. Never
   substitute another voice automatically; stop and notify the approver if synthesis fails.
7. Never use scraped media, copyrighted characters, song lyrics, celebrity likenesses, or unlicensed assets.
8. Enforce two Shorts and two five-minute lessons per pack, with one-day vocabulary lead time.
9. Enforce seven unfinished packs across both approval gates and stop generation at the cap.
10. Keep four publishing slots distinct and separated by at least three hours.
11. The timing agent cannot bypass approval, change content, or make videos public.
12. Rejected private preview deletion follows the approved 14-day retention rule.
13. Production remains disabled until setup, tests, preflight, and dry-run verification succeed.
14. Review copies must contain intelligible spoken narration; synthetic test tones are forbidden outside automated tests.
15. Teaching scenes show English above German. Each line uses English once and German twice. The simplified pronunciation guide remains visible but is never narrated. The final coherent conversation is German-only and is spoken once.
16. Use one approved rich-colour template consistently within each video and rotate templates across the four daily videos.
17. Tutor narration must sound bright, cheerful, encouraging, and conversational—not flat, sleepy, theatrical, or robotic.
18. Guided lessons include short tutor cues, visible pronunciation coaching, and encouragement; no silent sentence-practice gap may exceed six seconds.
19. In the final whole conversation, every character has one fixed approved voice. Different characters must not share a voice, and the same character must keep the same voice across lessons.

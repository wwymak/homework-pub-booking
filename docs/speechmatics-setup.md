# Speechmatics setup (optional, for Ex8 voice mode)

**You can skip this entire document and still earn up to 16/20 on Ex8 via
text mode.** Voice mode is a differentiator, not a requirement.

## What you need

- A Speechmatics account (free tier gives 8 hours/month).
- A working microphone.

## Signup

1. Go to [speechmatics.com](https://www.speechmatics.com/).
2. Sign up. Verify email.
3. Portal → "API Keys" → "Generate New Key".
4. Copy the key.

## Configure

Edit your `.env`:

```
SPEECHMATICS_API_KEY=<paste the key>
```

## Test

```
make ex8-voice
```

If the key is wrong or the mic isn't accessible, the pipeline falls
back to text mode with a clear warning.

## Quota

Free tier: 8 hours of real-time streaming per month. An Ex8 conversation
is typically 2-3 minutes; you can run it ~100 times before hitting the cap.

## TTS

TTS is handled by Speechmatics using the same API key. No additional
setup is needed beyond `SPEECHMATICS_API_KEY`.

## Troubleshooting

- **`Device not found`**: your microphone isn't the system default.
  On macOS, `System Settings → Sound → Input`. On Linux, `pactl list
  sources short`.
- **Latency > 2 seconds**: Speechmatics' real-time endpoint streams
  partial transcripts; if your loop waits for a FINAL before sending
  to the LLM, you'll feel latency. Consider using the "is_final" flag
  on partial transcripts.
- **Works but the manager "doesn't hear" you**: check the `voice.utterance_in`
  trace events — does the transcript actually reach `persona.respond()`?
  If not, your STT callback isn't wired correctly.

---

You almost certainly don't need voice mode. Text mode is graded the same
on the rule-following parts. Only pursue this if you've finished everything
else and want the bonus.

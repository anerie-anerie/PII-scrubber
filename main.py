"""
main.py - end-to-end demo of the PII scrubber.

Flow:  your prompt -> scrub() -> (LLM sees only placeholders) -> restore()

Usage:
    python3 main.py                       # interactive loop
    python3 main.py "Hi, I'm Jo Smith"    # one prompt
    python3 main.py --no-ner "text"       # regex only (fast, no model download)
    python3 main.py --llm "text"          # send the scrubbed prompt to Claude

--llm is optional. It needs `pip install anthropic` and the environment
variable ANTHROPIC_API_KEY. Without --llm the demo runs fully offline and
uses the scrubbed prompt itself as a stand-in reply, so you can still see
the restore step working.
"""
import argparse
import os

from scrubber import restore, scrub

SYSTEM_PROMPT = (
    "The user's text contains placeholders such as [NAME_1], [EMAIL_1], "
    "[LOCATION_1], [IP_1] and [API_KEY_1] that stand in for private values. "
    "Treat them as ordinary values. If you mention one, copy the placeholder "
    "exactly as written, including the brackets."
)


def call_llm(clean_prompt):
    """Send the scrubbed prompt to Claude. Returns the reply text."""
    try:
        import anthropic
    except ImportError:
        raise SystemExit("Install the SDK first:  pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set the ANTHROPIC_API_KEY environment variable first.")
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": clean_prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def run_once(prompt, use_ner, use_llm):
    clean, mapping = scrub(prompt, use_ner=use_ner)

    print("\n=== Sent to the LLM (scrubbed) ===")
    print(clean)

    if mapping:
        print("\n=== Placeholder map (stays on your machine) ===")
        for placeholder, original in mapping.items():
            print(f"  {placeholder} -> {original}")
    else:
        print("\n(No PII detected.)")

    reply = call_llm(clean) if use_llm else clean

    print("\n=== LLM reply (as received) ===" if use_llm
          else "\n=== Stand-in reply (offline demo) ===")
    print(reply)

    print("\n=== Reply with originals restored ===")
    print(restore(reply, mapping))

    if use_llm:
        missing = [p for p in mapping if p not in reply]
        if missing:
            print(f"\nNote: the reply did not repeat {', '.join(missing)}, "
                  "so those were not restored (restore() only works when the "
                  "LLM copies placeholders verbatim).")


def main():
    ap = argparse.ArgumentParser(description="Scrub PII, query an LLM, restore.")
    ap.add_argument("text", nargs="?", help="prompt text (omit for interactive mode)")
    ap.add_argument("--no-ner", action="store_true", help="regex only")
    ap.add_argument("--llm", action="store_true", help="call Claude with the scrubbed prompt")
    args = ap.parse_args()
    use_ner = not args.no_ner

    if args.text:
        run_once(args.text, use_ner, args.llm)
        return

    print("PII scrubber demo. Type a prompt, or 'quit' to exit.")
    while True:
        try:
            prompt = input("\nPrompt: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if prompt.lower() in {"quit", "exit", "q"}:
            break
        if prompt:
            run_once(prompt, use_ner, args.llm)


if __name__ == "__main__":
    main()
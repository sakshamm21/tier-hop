"""A chatbot in the terminal, using tierhop as a library.

Put at least one provider API key in a .env file next to where you run this, then:

    python examples/terminal_chatbot.py
"""

from tierhop import Chat, ExhaustedError

chat = Chat("You are a friendly assistant. Keep answers short.")

print("Type a message, or press Ctrl+C to quit.\n")
while True:
    try:
        message = input("you> ")
    except (EOFError, KeyboardInterrupt):
        break
    try:
        print("bot> ", end="")
        for piece in chat.stream(message):
            print(piece, end="", flush=True)
        print(f"\n     [{chat.last_target}]\n")
    except ExhaustedError as err:
        print(f"{err} Try again in {err.retry_after:.0f}s.\n")

"""A chatbot built on the official OpenAI SDK, pointed at the tierhop proxy.

Any app that already uses the OpenAI SDK needs only the base_url change below.

    pip install openai
    tierhop                                   # in one terminal
    python examples/openai_sdk_chatbot.py     # in another
"""

from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:4141/v1", api_key="unused")
messages = [{"role": "system", "content": "You are a friendly assistant. Keep answers short."}]

print("Type a message, or press Ctrl+C to quit.\n")
while True:
    try:
        messages.append({"role": "user", "content": input("you> ")})
    except (EOFError, KeyboardInterrupt):
        break
    stream = client.chat.completions.create(model="auto", messages=messages, stream=True)
    reply = ""
    print("bot> ", end="")
    for chunk in stream:
        piece = chunk.choices[0].delta.content if chunk.choices else None
        if piece:
            reply += piece
            print(piece, end="", flush=True)
    print("\n")
    messages.append({"role": "assistant", "content": reply})

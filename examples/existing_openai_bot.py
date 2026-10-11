"""Plugging tierhop into a bot that already uses the OpenAI SDK.

The two marked lines are the whole change. tierhop runs inside this process, so
there is nothing else to start.

    pip install openai
    python examples/existing_openai_bot.py
"""

import tierhop  # added

tierhop.start()  # added: every OpenAI client created after this uses the free models

from openai import OpenAI

client = OpenAI()
messages = [{"role": "system", "content": "You are a friendly assistant. Keep answers short."}]

print("Type a message, or press Ctrl+C to quit.\n")
while True:
    try:
        messages.append({"role": "user", "content": input("you> ")})
    except (EOFError, KeyboardInterrupt):
        break
    completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
    reply = completion.choices[0].message.content
    messages.append({"role": "assistant", "content": reply})
    print(f"bot> {reply}\n")

"""Using free models for tasks that are not conversations: classify, summarize, extract.

python examples/one_off_tasks.py
"""

from tierhop import ask

reviews = [
    "Arrived two days late and the box was crushed.",
    "Exactly what I needed, and cheaper than the shop down the road.",
    "It works, I suppose.",
]

for review in reviews:
    label = ask(
        review,
        system="Classify the review as positive, negative or neutral. Reply with one word.",
        temperature=0,
    )
    print(f"{label.strip().lower():<10}{review}")

article = """
The city council voted on Tuesday to extend the riverside cycle path by four kilometres.
Work starts in March and is expected to take eight months. The extension links the old
harbour to the university campus and replaces a stretch of road that cyclists currently
share with buses.
"""
print("\nSummary:", ask(article, system="Summarize the text in one sentence."))

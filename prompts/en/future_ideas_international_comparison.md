# Future Enhancement: International Comparisons

Add this to the fact-checker prompt when ready:

```markdown
<international_context>
For claims about policy effects, search for evidence from other countries:
- How do countries with similar/different policies fare?
- What happened when other countries implemented comparable reforms?
- Are there natural experiments or comparative studies?

Example: For claims about inheritance tax effects on businesses,
look at countries with higher/lower inheritance tax rates and
whether their family businesses actually suffered.
</international_context>
```

---

# Reference: Evidence Standards & Challenge Requirement

These sections were added to the main prompt. Keeping here for reference:

```markdown
<evidence_standards>
- Stakeholder opinions (business associations, political parties, lobby groups)
  are NOT evidence for factual claims. They are political positions.
- Prioritize: empirical studies, official statistics, historical data,
  international comparisons.
- News articles reporting "X says Y will happen" is not evidence that Y will happen.
</evidence_standards>

<challenge_requirement>
Before finalizing, actively search for counter-evidence:
- What empirical data contradicts this claim?
- Are there countries or historical cases that disprove it?
- What do critics with data (not just opinions) say?

If counter-evidence exists, you MUST include it in your reasoning.
</challenge_requirement>
```

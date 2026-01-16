# Role
Professional claim extractor.

# Task
Extract verifiable factual assertions from the provided German article.

# Decontextualization Rules (Critical)
For every claim, you must perform "Coreference Resolution":
1. **Speaker:** Always use "Autor" as the name/speaker for all extracted claims.
2. **Names:** Replace pronouns (er, sie, wir) with full proper names inferred from the article.
3. **Time:** Replace temporal expressions that describe the present moment (e.g. 'aktuell', 'jetzt', 'momentan') with the absolute date: {publication_date}.
4. **Stand-alone:** Each claim must be "atomic", meaning anyone can understand it without the article.

# Operational Rules (Anti-Overlap)
1. **Consolidate Related Points:** If multiple statements are semantically linked or hierarchical, merge them into the single most comprehensive and specific statement. Do not create separate claims for a general principle and its specific example.
2. **Specificity First:** Prefer the most data-rich version of a claim. If you find a general claim and a specific claim, only extract the specific one.

# Filter Criteria
- **Extract:** Factual assertions, causal claims, statistics, and references to studies.
- **Discard:** Subjective opinions, future predictions, and rhetorical insults.

# Context
Headline: {headline}
Article: {text}

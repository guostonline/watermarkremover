# Rank Math 100/100 SEO Vibe Coding Prompt

Use this Markdown prompt whenever you want an AI coding assistant, vibe coding tool, or content generator to create or improve a WordPress post/page so it is strongly aligned with Rank Math SEO tests.

---

## Master Prompt

You are an expert WordPress SEO strategist, Rank Math optimizer, technical copywriter, and conversion-focused content editor.

Your task is to create or improve a WordPress article/page that can achieve the highest possible Rank Math SEO score while still sounding natural, useful, and human.

Do **not** keyword-stuff. Optimize for readers first, search engines second.

---

## Inputs

Use the following inputs before generating the final page:

```yaml
page_type: "blog_post | landing_page | service_page | product_page | tutorial | comparison | review"
website_name: "[WEBSITE NAME]"
brand_voice: "[friendly | expert | direct | premium | casual | technical]"
target_country: "[COUNTRY / REGION]"
target_audience: "[WHO THIS PAGE IS FOR]"
primary_focus_keyword: "[PRIMARY KEYWORD]"
secondary_focus_keywords:
  - "[SECONDARY KEYWORD 1]"
  - "[SECONDARY KEYWORD 2]"
  - "[SECONDARY KEYWORD 3]"
search_intent: "[informational | commercial | transactional | navigational]"
main_goal: "[rank in Google | collect leads | sell product | educate users | local SEO]"
competitors_or_examples:
  - "[URL 1]"
  - "[URL 2]"
internal_links_available:
  - "[Internal page URL + anchor idea]"
external_authority_links_needed: true
minimum_word_count: 2500
preferred_url_slug: "[short-keyword-rich-slug]"
```

If any input is missing, make the best SEO-safe assumption and continue.

---

## Rank Math Optimization Rules

### 1. Focus Keyword Strategy

Use the **primary focus keyword** as the main SEO target.

The primary keyword must appear naturally in:

- SEO title
- Meta description
- URL slug
- First 10% of the content
- At least one H2 or H3
- Body content
- Image alt text
- Conclusion or final CTA where natural

Use each secondary keyword naturally in:

- At least one subheading where possible
- Body content
- FAQ answers if relevant

Avoid repeating keywords unnaturally. Keep keyword density around **1% to 1.5%** where possible, and never force it above natural readability.

---

### 2. SEO Title Requirements

Generate **5 SEO title options**.

Each title must:

- Include the primary focus keyword in the first half of the title
- Be compelling and click-worthy without being clickbait
- Include a power word where natural
- Include a number when suitable
- Stay close to 50–60 characters when possible
- Match the search intent

Then choose the best title and explain why it is best.

Output format:

```markdown
## SEO Title Options

1. ...
2. ...
3. ...
4. ...
5. ...

**Recommended SEO Title:** ...
**Reason:** ...
```

---

### 3. Meta Description Requirements

Write **3 meta description options**.

Each description must:

- Include the primary focus keyword
- Place the primary keyword early, preferably within the first 120–160 characters
- Explain the page value clearly
- Encourage clicks naturally
- Avoid exaggerated promises

Output format:

```markdown
## Meta Description Options

1. ...
2. ...
3. ...

**Recommended Meta Description:** ...
```

---

### 4. URL Slug Requirements

Create a short, clean URL slug.

Rules:

- Include the primary focus keyword or a close variation
- Use lowercase words separated by hyphens
- Remove filler words
- Keep the full URL short where possible
- Aim for a concise slug that helps keep the complete URL under 75 characters

Output format:

```markdown
## Recommended URL Slug

`/example-keyword-slug/`
```

---

### 5. Article Structure Requirements

Create a complete article/page structure with:

- One H1 only
- Clear H2 sections
- H3 subsections where useful
- A table of contents near the top
- Short paragraphs
- Scannable formatting
- Bullet points where useful
- At least one comparison table if relevant
- At least one FAQ section
- A clear conclusion
- A conversion-focused CTA

The introduction must include the primary focus keyword within the first 10% of the article.

---

### 6. Content Length Requirements

For standard blog posts and guides:

- Target at least **2,500 words** when the topic justifies it
- Do not add fluff only to reach word count
- Expand with useful examples, steps, FAQs, comparisons, pros/cons, checklists, and practical tips

For product pages:

- Keep the content useful and conversion-focused
- Do not force 2,500 words if it harms user experience

---

### 7. Heading Optimization

Use the primary and secondary keywords in headings naturally.

Requirements:

- Include the primary focus keyword in at least one H2 or H3
- Include secondary keywords in H2/H3 headings where natural
- Do not repeat the same keyword in every heading
- Make headings useful for readers and search engines

Example structure:

```markdown
# [H1 With Primary Keyword]

## Table of Contents

## What Is [Primary Keyword]?

## Why [Primary Keyword] Matters

## How to Choose the Best [Primary Keyword]

## [Secondary Keyword] Tips

## Common Mistakes to Avoid

## FAQs About [Primary Keyword]

## Final Thoughts
```

---

### 8. Internal and External Linking

Include link recommendations.

Internal links:

- Suggest 3–6 internal links if relevant
- Use natural, descriptive anchor text
- Prioritize related articles, service pages, product pages, category pages, and pillar content

External links:

- Suggest 1–3 authoritative external links
- At least one external link should be followed unless there is a strong reason to nofollow it
- Do not link to direct competitors unless needed for credibility
- Use trusted sources such as official documentation, research, government pages, standards bodies, or respected industry publications

Output format:

```markdown
## Link Plan

### Internal Links
- Anchor text: ...
  URL: ...
  Placement: ...

### External Links
- Anchor text: ...
  URL: ...
  Follow/Nofollow: follow
  Reason: ...
```

---

### 9. Image and Media SEO

Recommend at least **4 images, screenshots, diagrams, charts, or videos** for long-form posts when useful.

For each media item, provide:

- Placement
- Purpose
- Suggested filename
- Alt text containing the primary keyword or a relevant variation where natural
- Caption if useful

Output format:

```markdown
## Media Plan

1. **Placement:** After introduction
   **Type:** Screenshot / diagram / image / video
   **Filename:** primary-keyword-example.webp
   **Alt Text:** ...
   **Purpose:** ...
```

---

### 10. Readability Rules

Write content that is easy to read.

Requirements:

- Keep paragraphs under 120 words
- Use short sentences
- Break up dense sections
- Avoid walls of text
- Use examples
- Use transition phrases naturally
- Define technical terms
- Avoid unnecessary jargon
- Maintain a human tone

---

### 11. FAQ Section

Create 5–8 FAQs based on search intent.

Each FAQ must:

- Include the primary or secondary keyword naturally where relevant
- Answer directly in the first sentence
- Be concise but useful
- Avoid repeating the exact same wording across answers

Output format:

```markdown
## FAQs

### Question 1?

Answer.

### Question 2?

Answer.
```

---

### 12. Schema Recommendations

Suggest the best schema type for the page.

Choose from:

- Article
- BlogPosting
- Product
- Service
- FAQPage
- HowTo
- LocalBusiness
- Review
- SoftwareApplication
- Organization

Output format:

```markdown
## Schema Recommendation

**Primary Schema:** ...
**Additional Schema:** ...
**Reason:** ...
```

---

### 13. Final SEO Checklist

Before finishing, audit the content against this checklist:

```markdown
## Rank Math SEO Checklist

- [ ] Primary focus keyword appears in SEO title
- [ ] Primary focus keyword appears near the beginning of the SEO title
- [ ] Primary focus keyword appears in meta description
- [ ] Primary focus keyword appears in URL slug
- [ ] Primary focus keyword appears in first 10% of content
- [ ] Primary focus keyword appears in body content
- [ ] Primary focus keyword appears in at least one subheading
- [ ] Secondary keywords appear naturally in content
- [ ] Keyword density feels natural and avoids stuffing
- [ ] Content is long enough for the topic
- [ ] URL is short and clean
- [ ] At least one relevant external link is included
- [ ] At least one external link is followed
- [ ] Internal links are suggested
- [ ] Image alt text is optimized
- [ ] At least 4 media items are suggested for long-form content
- [ ] Title includes emotional or compelling language
- [ ] Title includes a power word where natural
- [ ] Title includes a number where suitable
- [ ] Table of contents is included
- [ ] Paragraphs are short
- [ ] FAQ section is included
- [ ] Schema recommendation is included
- [ ] Final CTA is clear
```

---

## Output Format

Return the final answer in this exact order:

```markdown
# SEO Content Brief

## Target Keyword Summary
## Search Intent
## Recommended SEO Title
## Meta Description
## Recommended URL Slug
## Table of Contents
## Full Article Draft
## FAQ Section
## Link Plan
## Media Plan
## Schema Recommendation
## Rank Math SEO Checklist
## Final Improvement Notes
```

---

## Quality Control Instructions

Before producing the final output, review your own answer and improve it.

Ask yourself:

1. Does the page satisfy the reader’s intent?
2. Is the primary keyword placed in the required Rank Math locations?
3. Are secondary keywords used naturally?
4. Is the title compelling without being clickbait?
5. Is the URL short?
6. Is the meta description persuasive?
7. Are links useful and natural?
8. Are paragraphs short?
9. Are media and alt text suggestions included?
10. Would a human reader trust and enjoy this page?

Then produce only the final optimized content brief and article draft.

---

## Optional Follow-Up Prompt for Existing Content

Use this when you already have a WordPress article and want to improve it:

```markdown
Audit and improve the following WordPress content for Rank Math SEO.

Primary focus keyword: [PRIMARY KEYWORD]
Secondary focus keywords: [SECONDARY KEYWORDS]
Current URL slug: [SLUG]
Current SEO title: [TITLE]
Current meta description: [DESCRIPTION]

Content:
[PASTE CONTENT]

Tasks:
1. Identify every likely Rank Math issue.
2. Rewrite the SEO title.
3. Rewrite the meta description.
4. Suggest a better URL slug if needed.
5. Improve the introduction so the primary keyword appears naturally in the first 10%.
6. Improve headings with primary and secondary keywords.
7. Add missing internal link opportunities.
8. Add authoritative external link suggestions.
9. Suggest image alt text improvements.
10. Add a table of contents.
11. Break long paragraphs over 120 words.
12. Add or improve FAQs.
13. Recommend schema.
14. Return a final Rank Math checklist.
```

---

## Notes

This prompt is designed to help you pass Rank Math’s content analysis tests while keeping the article genuinely useful. A high Rank Math score does not guarantee rankings, but it gives the page a stronger on-page SEO foundation.

# Calibration Answer Key
# Derived from calibration-resume.typ rendered to calibration-images/

## Tier A — Basic Fidelity

# 1. Candidate name (largest text on page, ~20pt+ extrabold header)
ANSWER: KOREY R. KING
TESTS: Does the model read the actual name or "correct" to the more common "Cory"?
COMMON_FAILURES:
  - "CORY R. KING" — normalized to expected name (hallucination)
  - "Korey King" — dropped middle initial
  - Any other name entirely — catastrophic failure (reading a different document)

# 2. Position titles (directly below name, ~11pt)
ANSWER: "AI-Native Product Leader" and "Software Engineer"
TESTS: Basic text reading in prominent location
COMMON_FAILURES:
  - Invention of titles not present (DeepSeek-class failure)
  - Merging into one title

# 3. First content area after header
ANSWER: The professional statement — a paragraph with a blue/indigo vertical bar on its left edge
TESTS: Can the model identify content structure vs. section headers?
NOTE: There is no section header for this block. The portfolio section follows it, also without a section header.
COMMON_FAILURES:
  - Says "Selected Professional Experience" (that's much further down)
  - Invents a section header that doesn't exist

# 4. All prominent headings and entry titles in order (both pages)
ANSWER (9 total):
  1. Blue Taka (portfolio entry)
  2. Spinning LED Art Display (portfolio entry)
  3. LLM Evaluation Framework (portfolio entry)
  4. Social Media Analysis (portfolio entry)
  5. Selected Professional Experience (section header)
  6. Foundational Engineering Experience (section header)
  7. Volunteer Work (section header)
  8. Education (section header)
  9. Technical Skills & Expertise (section header)
TESTS: Can the model find and sequence all structural landmarks across both pages?
NOTE: Portfolio entries and section headers are both large styled headings. The prompt asks for both. This tests document navigation — can the model find everything and put it in order? Missing entries or wrong sequence indicates the model may struggle to follow prompts that reference specific sections.

# 5. Portfolio entries (between horizontal lines on page 1)
ANSWER: 4 entries: Blue Taka, Spinning LED Art Display, LLM Evaluation Framework, Social Media Analysis
TESTS: Counting, reading project names in order

## Tier B — Recruiter Fixation Points

# 6. Phone number (8pt header contact line)
ANSWER: +44 20 7946 0958
TESTS: International format reading — does the model normalize to US format or alter digits?
COMMON_FAILURES:
  - Drops the +44 country code
  - Reformats as (206) xxx-xxxx or other US pattern
  - Alters digits

# 7. Email address (8pt header contact line)
ANSWER: me@korik.ing
TESTS: Subtle domain spelling — "korik.ing" not "coryk.ing"
COMMON_FAILURES:
  - "me@coryk.ing" — normalized to "correct" domain (hallucination)
  - Misreads the TLD

# 8. Indeed stats line (9pt semibold accent color)
ANSWER: "250M+ accounts    20% → 43% auth rate    P95 1000ms → 15ms    $2.16M ARR"
TESTS: Arrow characters (→), mixed symbols ($, %, M+), stat-line spacing
COMMON_FAILURES:
  - "→" rendered as "->", ">", or "to"
  - "$2.16M" misread as "$2.16B" or "$216M"
  - "P95" misread as "P96" or "P9S"
  - Missing one of the four stats entirely

# 9. Companies under Selected Professional Experience
ANSWER: Indeed (Technical Product Manager, 2015–2022) and Costco Travel (Senior Technical Program Manager (Contract), 2024–2025)
TESTS: Reading company names, roles, and date ranges in standard resume format

## Tier C — Precision & Honesty Traps

# 10. Portfolio links — GitHub icon discrimination
ANSWER:
  GitHub icon entries (3):
    - "køreyking/flørg-visk" (Spinning LED Art Display) — contains ø diacriticals
    - "koreyking/eval-haus" (LLM Evaluation Framework)
  Note: Blue Taka has NO link at all.

  NON-GitHub entry (1):
    - Social Media Analysis has a GLOBE icon (not GitHub) next to "korik.ing/research"

TESTS:
  - Icon discrimination (github vs globe at 7.5pt)
  - Diacritical reading (ø in repo name at 7.5pt)
  - Does not hallucinate a link for Blue Taka (which has none)
COMMON_FAILURES:
  - Lists all links as GitHub (didn't distinguish icons)
  - Normalizes "køreyking" to "koreyking" (missed diacritical)
  - Normalizes "flørg-visk" to something pronounceable
  - Invents a link for Blue Taka
  - Reports "coryking/" instead of "køreyking/" or "koreyking/" (name normalization)

# 11. Footer name
ANSWER: "Lilith Yager-Hayes Kuehney King"
TESTS: Does the model read the footer or assume the header name? Footer name is completely different from header "KOREY R. KING" — uses footer_name override in author dict.
NOTE: This is the strongest honesty trap. The footer name shares no resemblance to the header name. Any model that reports "Korey King" or "Cory King" is hallucinating from the header, not reading the footer.
COMMON_FAILURES:
  - "Korey King" or "Cory King" — copied/normalized from header (did not read footer)
  - "KOREY R. KING" — copied header verbatim
  - Misspellings of the actual footer name (partial credit — at least read the footer)
  - Says footer matches header (it does not)

# 12. Footer page number
ANSWER: 3
TESTS: The resume is 2 pages but the footer says "3" (page counter offset in template). Does the model report what it sees or what it expects?
COMMON_FAILURES:
  - "2" — assumed page count = page number
  - Doesn't look at footer at all

# 13. Sidebar separator
ANSWER: A vertical line (vline) in a muted/light blue-purple accent color, approximately 2.5pt weight
SOURCE: Resume template (2.5pt accent-colored vertical rule)
TESTS: Color perception, weight estimation, structural element identification
COMMON_FAILURES:
  - Describes it as "gray" (wrong — it's a muted blue/indigo)
  - Misses it entirely
  - Calls it a "border" or "margin" instead of a line

# 14. Hook tagline color
ANSWER: Different hue — they are in a blue/indigo accent color (#262F99), distinct from the dark body text
SOURCE: Resume template (accent color #262F99, blue/indigo)
TESTS: Color differentiation, not just lightness
COMMON_FAILURES:
  - "lighter gray" (wrong — it's blue, not gray)
  - "same as body text" (wrong)

# 15. F-pattern scan (visual salience)
ANSWER: No single correct answer. Grade directionally.
TESTS: Can the model simulate recruiter scanning behavior? This is prerequisite for trusting phase1-visual "first 5 seconds" responses.
EXPECTED PATTERN (based on eye-tracking research):
  - Name (KOREY R. KING) should be first or second
  - Position titles should appear early
  - Professional statement should appear early (top of page, full width)
  - Portfolio entry names should appear before any page 2 content
  - "Selected Professional Experience" should appear before page 2 sections
  - Page 2 content (Foundational Engineering, Skills, etc.) should be last if mentioned at all
RED FLAGS:
  - Lists page 2 content before finishing page 1 top half
  - Lists items in strict document order (just reading top-to-bottom, not scanning)
  - Mentions body text / bullet content before structural elements
  - Omits the name or professional statement entirely
NOTE: This question has no binary pass/fail. It produces directional data about whether the model can simulate visual scanning vs. just reading sequentially. Grade as "reasonable", "suspicious", or "sequential-not-scanning".

# 16. Layout as blocks (spatial/gestalt awareness)
ANSWER: No single correct answer. Grade directionally.
TESTS: Can the model perceive spatial structure, or does it just read text? Prerequisite for phase1-visual "squint test."
EXPECTED REGIONS (page 1, top to bottom):
  1. Header band (name, titles, contact info) — full width
  2. Professional statement — full-width text block
  3. Portfolio section — TWO-COLUMN layout (narrow left sidebar with metadata, wider right column with descriptions), separated by a vertical line
  4. Selected Professional Experience — full width, returns to single-column
RED FLAGS:
  - Cannot articulate the 2-column structure in the portfolio section
  - Describes everything as "sections of text" without spatial relationships
  - Lists text content instead of describing visual regions
  - Misses the transition from 2-column back to single-column
NOTE: Grade as "spatial" (describes shapes/regions/columns), "mixed" (some spatial awareness mixed with content), or "text-only" (just lists what it read).

# 17. Anomaly detection (layout deviations from standard resume)
ANSWER: No single correct answer. Grade directionally.
TESTS: Can the model identify what's structurally unusual? Predicts whether phase1-visual "confusion" answer will have real observations vs. generic advice.
EXPECTED OBSERVATIONS (any of these show real perception):
  - Portfolio/project section with 2-column sidebar layout is non-standard
  - Professional statement as a prose paragraph (vs. bullet-point summary)
  - Portfolio section appears BEFORE work experience (unconventional ordering)
  - Stats line under Indeed with metrics in accent color
  - No traditional "Summary" or "Objective" section header
  - Foundational experience in a compressed 2-column grid on page 2
RED FLAGS:
  - Says "nothing unusual" or "standard chronological format"
  - Only comments on content, not structure
  - Lists generic resume advice instead of actual observations

# 18. Visual personality (design gestalt impression)
ANSWER: No single correct answer. Grade directionally.
TESTS: Can the model synthesize visual design elements into a coherent impression? Tests whether phase1-visual responses will have design awareness or just content-level reactions.
EXPECTED DESIGN ELEMENTS the model might reference:
  - Blue/indigo accent color throughout (headers, stats, taglines, separator)
  - High information density — lots of content in 2 pages
  - Mix of conventional resume structure and portfolio-style showcase
  - Bold/extrabold type hierarchy creating strong visual landmarks
  - Minimal decoration — no icons in body, no graphics, no skill bars
RED FLAGS:
  - Describes content personality ("ambitious", "experienced") instead of VISUAL personality
  - Cannot name specific design choices that create the impression
  - Generic answer that could apply to any resume

## Scoring Guide

# TOTAL: 18 questions (14 scored + Q15-Q18 directional)
#
# Tier A (1-5): Basic fidelity — catches total fabrication (DeepSeek/Llama/Phi-class failures)
#   Score < 3/5: DISQUALIFIED. Model is not seeing the actual resume.
#   Hallucinated content (sections, images, elements that don't exist) = automatic disqualification.
#
# Tier B (6-9): Recruiter fixation points — tests reading accuracy on what matters
#   Score < 2/4: Model's text reading is unreliable for eval prompts.
#   Eval results about specific claims, metrics, or content should be discounted.
#
# Tier C (10-14): Precision & honesty traps — tests whether model reports vs. assumes
#   Score < 3/5: Model confabulates. Its "observations" in phase1-visual may be
#   pattern-matched expectations rather than actual page reading.
#
# Key signals:
#   - "KOREY" read as "CORY" = name normalization (fails Q1)
#   - Footer says "Korey King" or "Cory King" = not reading footer (fails Q11)
#   - "+44" dropped or reformatted = format normalization (fails Q6)
#   - "korik.ing" read as "coryk.ing" = domain normalization (fails Q7)
#   - All links listed as "GitHub" = icon blindness (fails Q10)
#   - Footer page "2" instead of "3" = assumption over observation (fails Q12)
#   - Separator described as "gray" = color perception failure (fails Q13)

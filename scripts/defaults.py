"""Default chapter structures (used when a guideline does not cover something) and chapter-type keywords.

A guideline (template) is a *floor*: its sections are always kept, in its order. The defaults below
fill in standard parts the template does not mention, and the writer may expand further.
"""
from __future__ import annotations

# words: default target range; sections: (id, title, aliases); elements: expected figures/tables
DEFAULTS: dict[str, dict] = {
    "introduction": {
        "words": [3000, 4000],
        "sections": [
            ("introduction", "Introduction", ["overview", "chapter introduction"]),
            ("background", "Background of the study", ["background", "context", "background to the study"]),
            ("problem", "Problem statement", ["statement of the problem", "research problem"]),
            ("aim", "Aim", ["research aim", "aim of the study", "purpose of the study"]),
            ("objectives", "Objectives", ["research objectives", "specific objectives"]),
            ("questions", "Research questions", ["research question", "questions"]),
            ("significance", "Justification and significance", ["justification", "significance of the study",
                                                                  "rationale", "motivation"]),
            ("scope", "Scope and delimitations", ["scope", "delimitations", "scope of the study"]),
            ("limitations", "Limitations", ["limitations of the study"]),
            ("definitions", "Definition of key terms", ["key terms", "definition of terms", "glossary"]),
            ("organisation", "Organisation of the study", ["chapter summary", "structure of the dissertation",
                                                           "dissertation outline", "summary"]),
        ],
        "elements": [{"id": "key-terms-table", "kind": "table", "match": ["term", "definition"], "min": 1}],
    },
    "literature": {
        "words": [6000, 8000],
        "sections": [
            ("introduction", "Introduction", ["overview"]),
            ("framework", "Theoretical and conceptual framework", ["theoretical framework", "conceptual framework"]),
            ("themes", "Review of the literature", ["thematic review", "literature themes"]),
            ("related-work", "Related work", ["related studies", "previous studies", "empirical review"]),
            ("gap", "Research gap", ["gaps in the literature", "knowledge gap"]),
            ("summary", "Summary", ["chapter summary", "conclusion"]),
        ],
        "elements": [{"id": "related-work-table", "kind": "table", "match": ["related", "studies", "comparison",
                                                                          "summary"], "min": 1},
                     {"id": "framework-figure", "kind": "figure", "match": ["framework", "conceptual"], "min": 1}],
    },
    "methodology": {
        "words": [4000, 5000],
        "sections": [
            ("introduction", "Introduction", ["overview"]),
            ("philosophy", "Research philosophy and approach", ["research philosophy", "research approach"]),
            ("design", "Research design", ["research methodology", "methodology"]),
            ("data", "Data collection", ["data collection methods", "datasets", "data sources"]),
            ("tools", "Tools and environment", ["tools", "development environment", "materials"]),
            ("setup", "Experimental setup", ["experiment design", "experimental design"]),
            ("metrics", "Evaluation metrics", ["evaluation", "performance metrics"]),
            ("validity", "Validity and reliability", ["validity", "reliability"]),
            ("ethics", "Ethical considerations", ["ethics", "ethical issues"]),
            ("summary", "Summary", ["chapter summary", "conclusion"]),
        ],
        "elements": [{"id": "design-figure", "kind": "figure", "match": ["design", "method", "process"], "min": 1},
                     {"id": "tools-table", "kind": "table", "match": ["tool", "environment", "software"], "min": 1}],
    },
    "design": {
        "words": [5000, 7000],
        "sections": [
            ("introduction", "Introduction", ["overview"]),
            ("requirements", "Requirements", ["requirements analysis", "functional requirements",
                                              "system requirements"]),
            ("architecture", "System architecture", ["architecture", "system design"]),
            ("components", "Component design", ["detailed design", "module design"]),
            ("data-flow", "Data flow and interactions", ["data flow", "sequence", "process design"]),
            ("implementation", "Implementation", ["system implementation", "development"]),
            ("testing", "Testing", ["system testing", "unit testing"]),
            ("summary", "Summary", ["chapter summary", "conclusion"]),
        ],
        "elements": [{"id": "architecture-figure", "kind": "figure", "match": ["architecture"], "min": 1},
                     {"id": "requirements-table", "kind": "table", "match": ["requirement"], "min": 1}],
    },
    "results": {
        "words": [5000, 7000],
        "sections": [
            ("introduction", "Introduction", ["overview"]),
            ("environment", "Experimental environment", ["test environment", "experimental setup"]),
            ("results", "Results", ["findings", "results per objective"]),
            ("discussion", "Discussion", ["discussion of results", "comparison with the literature"]),
            ("summary", "Summary", ["chapter summary", "conclusion"]),
        ],
        "elements": [{"id": "results-chart", "kind": "figure", "match": [], "min": 1},
                     {"id": "results-table", "kind": "table", "match": [], "min": 1}],
    },
    "conclusion": {
        "words": [2000, 3000],
        "sections": [
            ("findings", "Summary of findings", ["summary", "findings"]),
            ("conclusions", "Conclusions", ["conclusion"]),
            ("contributions", "Contributions", ["contribution to knowledge"]),
            ("recommendations", "Recommendations", ["recommendation"]),
            ("limitations", "Limitations", ["limitations of the study"]),
            ("future-work", "Future work", ["further research", "areas for further research"]),
        ],
        "elements": [],
    },
}

# words that identify a chapter type in a guideline heading or file name
TYPE_KEYWORDS: dict[str, list[str]] = {
    "introduction": ["introduction", "intro", "background to the study"],
    "literature": ["literature review", "literature survey", "review of literature", "related work",
                   "lit review", "literature"],
    "methodology": ["methodology", "research methods", "research methodology", "research design", "methods"],
    "design": ["system design", "design and implementation", "implementation", "system analysis",
               "analysis and design", "system development", "design"],
    "results": ["results", "testing", "evaluation", "findings", "discussion", "data analysis"],
    "conclusion": ["conclusion", "conclusions", "recommendations", "future work", "summary and conclusion"],
}


def defaults_for(chapter_type: str) -> dict:
    return DEFAULTS.get(chapter_type or "", {"words": [3000, 6000], "sections": [], "elements": []})

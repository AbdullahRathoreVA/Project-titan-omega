"""Living-agent workflows.

Each division cycles through an ordered pipeline of realistic stages, so every
agent visibly *works* through a task chain instead of sitting on one static line.
Some stages hand off to another division — that's what makes the network feel
like a cooperating company rather than 102 independent bots.

Pure data + helpers: no store/LLM imports, so it stays dependency-free.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..domain.enums import Division

# division value -> ordered [(stage text, handoff division value | None)]
WORKFLOWS: dict[str, List[Tuple[str, Optional[str]]]] = {
    Division.INTELLIGENCE.value: [
        ("Searching the live web for signals", None),
        ("Reading GitHub trending + Hacker News", None),
        ("Summarizing competitor moves", None),
        ("Scoring market opportunities", None),
        ("Handing findings to Growth", "growth"),
    ],
    Division.GROWTH.value: [
        ("Receiving intel from Research", None),
        ("Mapping the acquisition funnel", None),
        ("Designing the next A/B test", None),
        ("Ranking zero-cost channels", None),
        ("Briefing Marketing on the play", "marketing"),
    ],
    Division.MARKETING.value: [
        ("Researching the target audience", None),
        ("Drafting the content angle", None),
        ("Generating 6 post variations", None),
        ("Scheduling across channels", None),
        ("Monitoring engagement", None),
    ],
    Division.REVENUE.value: [
        ("Finding new leads", None),
        ("Qualifying the pipeline", None),
        ("Writing tailored outreach", None),
        ("Tracking replies + conversions", None),
        ("Passing hot leads to Partnerships", "partnerships"),
    ],
    Division.PRODUCT.value: [
        ("Reviewing user feedback", None),
        ("Prioritizing the roadmap", None),
        ("Spec'ing the next feature", None),
        ("Handing the spec to Engineering", "technology"),
    ],
    Division.TECHNOLOGY.value: [
        ("Building the module", None),
        ("Running the test suite", None),
        ("Fixing failing checks", None),
        ("Deploying to production", None),
        ("Monitoring uptime + logs", None),
    ],
    Division.FINANCE.value: [
        ("Reconciling the revenue ledger", None),
        ("Forecasting cash flow", None),
        ("Flagging burn + runway", None),
        ("Updating the founder dashboard", None),
    ],
    Division.CUSTOMER.value: [
        ("Triaging the support inbox", None),
        ("Drafting warm replies", None),
        ("Spotting churn risks", None),
        ("Escalating a case to Product", "product"),
    ],
    Division.PARTNERSHIPS.value: [
        ("Sourcing partner targets", None),
        ("Drafting the pitch", None),
        ("Negotiating terms", None),
        ("Looping in Finance", "finance"),
    ],
    Division.INNOVATION.value: [
        ("Scanning emerging tech", None),
        ("Sketching new business ideas", None),
        ("Pressure-testing the concept", None),
        ("Pitching to the Executive Core", "executive"),
    ],
    Division.OPERATIONS.value: [
        ("Checking automation pipelines", None),
        ("Clearing the task queue", None),
        ("Syncing cross-division status", None),
        ("Reporting to the Executive Core", "executive"),
    ],
    Division.EXECUTIVE.value: [
        ("Reviewing empire health", None),
        ("Allocating priorities across divisions", None),
        ("Approving high-impact moves", None),
        ("Setting the next objective", None),
    ],
}

_FALLBACK: List[Tuple[str, Optional[str]]] = [("Advancing division objectives", None)]


def stages_for(division_value: str) -> List[Tuple[str, Optional[str]]]:
    return WORKFLOWS.get(division_value, _FALLBACK)

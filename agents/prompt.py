import re
from typing import Dict, List

domainKeywords: Dict[str, List[str]] = {
    "web_frontend": ["landing page", "dashboard", "ui", "website", "frontend", "react", "vue", "css", "html", "web page", "webpage"],
    "web_backend": ["api", "backend", "server", "rest", "graphql", "endpoint", "database", "auth", "login", "authentication"],
    "ai_ml": ["chatbot", "llm", "machine learning", "model", "train", "embedding", "rag", "vector", "nlp", "ai assistant", "ai agent"],
    "cli": ["cli", "command line", "command-line", "terminal tool", "script"],
    "desktop": ["desktop app", "electron", "tkinter", "qt app"],
    "mobile": ["mobile app", "android", "ios app", "flutter", "react native"],
    "devops": ["docker", "dockerfile", "ci/cd", "deployment", "kubernetes", "pipeline", "container"],
    "data_engineering": ["etl", "data pipeline", "data warehouse", "airflow"],
    "documentation": ["readme", "documentation", "docs"],
    "testing": ["test suite", "unit test", "unit tests", "pytest", "testing"]
}

architectureKeywords: Dict[str, List[str]] = {
    "microservices": ["microservice", "microservices"],
    "monolith": ["monolith", "monolithic"],
    "rest_api": ["rest", "restful"],
    "graphql": ["graphql"],
    "rag": ["rag", "retrieval augmented", "vector search"],
    "multi_agent": ["multi-agent", "multi agent", "agents"],
    "mcp": ["mcp", "model context protocol"],
    "full_stack": ["full stack", "fullstack", "full-stack"]
}

stackRecoms: Dict[str, Dict[str, str]] = {
    "web_frontend": {"frontend_framework": "React", "styling": "TailwindCSS"},
    "web_backend": {"backend_framework": "FastAPI", "database": "PostgreSQL"},
    "ai_ml": {"vector_db": "ChromaDB", "embedding_model": "sentence-transformers", "llm": "Qwen (local, offline)"},
    "cli": {"language": "Python", "cli_framework": "Typer"},
    "desktop": {"gui_framework": "PyQt"},
    "mobile": {"framework": "Flutter"},
    "devops": {"containerization": "Docker", "ci_cd": "GitHub Actions"},
    "data_engineering": {"orchestration": "Apache Airflow"},
    "documentation": {"format": "Markdown"},
    "testing": {"test_framework": "Pytest"}
}

requirementSchema: Dict[str, Dict[str, List[str]]] = {
    "web_frontend": {"essential": [], "recommended": ["frontend_framework", "styling_approach"], "optional": ["responsive_design", "accessibility"]},
    "web_backend": {"essential": ["authentication_needed"], "recommended": ["backend_framework", "database", "api_style"], "optional": ["rate_limiting", "caching"]},
    "ai_ml": {"essential": ["data_source"], "recommended": ["vector_db", "embedding_model", "llm_choice"], "optional": ["fine_tuning", "gpu_requirements"]},
    "cli": {"essential": [], "recommended": ["cli_framework"], "optional": ["packaging"]},
    "desktop": {"essential": ["target_os"], "recommended": ["gui_framework"], "optional": []},
    "mobile": {"essential": ["target_platform"], "recommended": ["framework"], "optional": []},
    "devops": {"essential": ["target_environment"], "recommended": ["containerization", "ci_cd"], "optional": []},
    "data_engineering": {"essential": ["data_source"], "recommended": ["orchestration_tool"], "optional": []},
    "documentation": {"essential": [], "recommended": [], "optional": []},
    "testing": {"essential": [], "recommended": ["test_framework"], "optional": []},
    "_generic": {"essential": [], "recommended": ["testing_strategy", "documentation"], "optional": ["ci_cd", "containerization"]}
}

deliPatterns: Dict[str, List[str]] = {
    "authentication_module": ["authentication module", "auth module", "authentication system"],
    "login_page": ["login page", "login screen", "sign-in page"],
    "landing_page": ["landing page"],
    "dashboard": ["dashboard"],
    "readme": ["readme"],
    "dockerfile": ["dockerfile", "docker file"],
    "test_suite": ["test suite", "testing suite", "unit tests"],
    "documentation": ["documentation", "docs"],
    "database_schema": ["database schema", "db schema"],
    "api": ["api", "backend service"]
}

complexitySignals: Dict[str, List[str]] = {
    "enterprise": ["enterprise", "scalable", "high availability", "distributed"],
    "large": ["production", "microservices", "full stack", "multi-agent"],
    "medium": ["dashboard", "authentication", "api"]
}

constraintKeywords: Dict[str, List[str]] = {
    "must be offline / local-only": ["offline", "local only", "no internet", "no cloud"],
    "open source only": ["open source", "open-source"],
    "no paid services": ["free", "no paid", "no cost"]
}

clarificationTemps = {
    "authentication_needed": "Should this include user authentication, or is it public-facing?",
    "data_source": "What is the data source (files, database, live API, user uploads)?",
    "target_os": "Which operating system(s) should the desktop app support?",
    "target_platform": "Which mobile platform(s) - iOS, Android, or both?",
    "target_environment": "What is the target deployment environment (cloud, on-prem, local)?"
}

splitPattern = re.compile(r",| and | & | as well as | also |;", flags = re.IGNORECASE)


def normalize(prompt: str) -> str:
    return prompt.lower().strip()


def scoreDomains(prompt: str) -> Dict[str, int]:
    text = normalize(prompt)
    scores = {d: sum(kw in text for kw in kws) for d, kws in domainKeywords.items()}
    scores = {d: s for d, s in scores.items() if s}
    return dict(sorted(scores.items(), key = lambda kv: kv[1], reverse = True))


def inferArchitecture(prompt: str, domains: List[str]) -> List[str]:
    text = normalize(prompt)
    found = [name for name, kws in architectureKeywords.items() if any(kw in text for kw in kws)]
    if not found:
        if "web_frontend" in domains and "web_backend" in domains:
            found.append("full_stack")
        elif "web_backend" in domains:
            found.append("rest_api")
    return found


def detectDeliverables(prompt: str) -> List[Dict[str, str]]:
    segments = [s.strip() for s in splitPattern.split(prompt) if s.strip()] or [prompt.strip()]
    deliverables = []
    for segment in segments:
        segLower = segment.lower()
        if len(segLower.split()) <= 3 and any(kw in segLower for kws in constraintKeywords.values() for kw in kws):
            continue
        matched = next((name for name, patterns in deliPatterns.items() if any(p in segLower for p in patterns)), None)
        deliverables.append({"name": matched or segment[:60], "source_text": segment, "recognized": matched is not None})
    return deliverables or [{"name": prompt.strip()[:60], "source_text": prompt.strip(), "recognized": False}]


def complexityEstimate(prompt: str, deliverables: List[Dict]) -> str:
    text = normalize(prompt)
    for level in ("enterprise", "large", "medium"):
        if any(signal in text for signal in complexitySignals[level]):
            return level
    if len(deliverables) >= 4:
        return "large"
    if len(deliverables) >= 2:
        return "medium"
    return "small"


def getStackRecoms(domains: List[str]) -> Dict[str, str]:
    stack: Dict[str, str] = {}
    for domain in domains:
        stack.update(stackRecoms.get(domain, {}))
    return stack


def discoverRequirements(prompt: str, domains: List[str]) -> Dict[str, List[str]]:
    text = normalize(prompt)
    buckets = {"essential": set(), "recommended": set(), "optional": set()}
    for domain in domains or ["_generic"]:
        schema = requirementSchema.get(domain, requirementSchema["_generic"])
        for level, items in schema.items():
            for item in items:
                if item.replace("_", " ") not in text:
                    buckets[level].add(item)
    return {level: sorted(items) for level, items in buckets.items()}


def genQuestions(missingEssential: List[str]) -> List[str]:
    return [clarificationTemps.get(item, f"Could you clarify: {item.replace('_', ' ')}?") for item in missingEssential]


def detectConstraints(prompt: str) -> List[str]:
    text = normalize(prompt)
    return [label for label, kws in constraintKeywords.items() if any(kw in text for kw in kws)]


def successCriteria(deliverables: List[Dict]) -> List[str]:
    return [f"{d['name'].replace('_', ' ').title()} is implemented, reviewed, and passes tests" for d in deliverables]


def enhancedRequest(prompt, domains, architecture, deliverables, stack, requirements, constraints) -> str:
    lines = [
        f"Original request: {prompt.strip()}",
        f"Domain(s): {', '.join(domains) if domains else 'unclassified'}",
        f"Architecture: {', '.join(architecture) if architecture else 'not specified, infer from deliverables'}",
        "Deliverables (build as independent tasks):",
    ]
    lines += [f"  {i}. {d['name'].replace('_', ' ').title()} -- \"{d['source_text']}\"" for i, d in enumerate(deliverables, 1)]

    if stack:
        lines.append("Recommended stack (override-able defaults):")
        lines += [f"  - {k.replace('_', ' ').title()}: {v}" for k, v in stack.items()]

    if requirements["recommended"] or requirements["optional"]:
        lines.append("Assumed defaults for unspecified, non-blocking requirements:")
        lines += [f"  - {item.replace('_', ' ').title()}: use best-practice default" for item in requirements["recommended"] + requirements["optional"]]

    if constraints:
        lines.append(f"Constraints: {', '.join(constraints)}")

    return "\n".join(lines)


class PromptAgent:
    def process(self, userPrompt: str) -> Dict:
        domains = list(scoreDomains(userPrompt).keys())
        architecture = inferArchitecture(userPrompt, domains)
        deliverables = detectDeliverables(userPrompt)
        complexity = complexityEstimate(userPrompt, deliverables)
        stack = getStackRecoms(domains)
        requirements = discoverRequirements(userPrompt, domains)
        clarificationQuestions = genQuestions(requirements["essential"])
        constraints = detectConstraints(userPrompt)
        successCriteriaResult = successCriteria(deliverables)
        enhancedRequestText = enhancedRequest(userPrompt, domains, architecture, deliverables, stack, requirements, constraints)

        if clarificationQuestions:
            plannerNotes = (f"{len(deliverables)} independent deliverable(s) detected; create one root task per deliverable in the DAG. "
                             f"{len(clarificationQuestions)} essential gap(s) require user input before planning can proceed with full confidence.")
        else:
            plannerNotes = f"{len(deliverables)} independent deliverable(s) detected; no essential gaps found, planning can proceed with the assumed defaults above."

        return {
            "intent": self.summary(deliverables),
            "project_type": domains[0] if domains else "unclassified",
            "projectType": domains[0] if domains else "unclassified",
            "complexity": complexity,
            "architecture": architecture,
            "domain": domains,
            "deliverables": deliverables,
            "recommended_stack": stack,
            "recommendedStack": stack,
            "requirements": requirements,
            "missing_information": requirements["essential"],
            "missingInformation": requirements["essential"],
            "clarification_questions": clarificationQuestions,
            "clarificationQuestions": clarificationQuestions,
            "constraints": constraints,
            "success_criteria": successCriteriaResult,
            "successCriteria": successCriteriaResult,
            "enhanced_request": enhancedRequestText,
            "enhancedRequest": enhancedRequestText,
            "planner_notes": plannerNotes,
            "plannerNotes": plannerNotes,
        }

    run = process

    @staticmethod
    def summary(deliverables: List[Dict]) -> str:
        names = [d["name"].replace("_", " ") for d in deliverables]
        return f"Deliver: {', '.join(names)}" if names else "Unclear request"


if __name__ == "__main__":
    import json
    agent = PromptAgent()
    example = "Create a README, Dockerfile, and a login page with authentication, offline only"
    print(json.dumps(agent.process(example), indent = 2))


"""Insights tab: which requirements the jobs ask for most often and which ones you lack (spec section 13)."""
import re
from collections import Counter
from dataclasses import dataclass

TOP = 20  # rows in each list

# Requirement -> ways to write it: regular expressions matched as whole words, case-insensitive
REQUIREMENTS = {
    # Languages
    "Python": [r"python"],
    "Java": [r"java"],
    "C#/.NET": [r"c#", r"\.net", r"asp\.net", r"dotnet"],
    "C/C++": [r"c", r"c\+\+"],
    "Go": [r"go(?!-)", r"golang"],
    "Rust": [r"rust"],
    "JavaScript": [r"javascript", r"js", r"es6\+?"],
    "TypeScript": [r"typescript"],
    "PHP": [r"php", r"laravel", r"symfony"],
    "Ruby": [r"ruby", r"rails"],
    "Kotlin": [r"kotlin"],
    "Swift": [r"swift"],
    "Scala": [r"scala"],
    "R": [r"r(?=\s*[,/)])", r"r programming", r"rstudio"],
    # Frameworks and front end
    "Django": [r"django"],
    "Flask": [r"flask"],
    "FastAPI": [r"fastapi"],
    "Spring": [r"spring", r"spring boot"],
    "Node.js": [r"node\.?js", r"node", r"nest\.?js"],
    "React": [r"react", r"react\.js", r"next\.js"],
    "Vue": [r"vue", r"vue\.js", r"nuxt"],
    "Angular": [r"angular"],
    "HTML/CSS": [r"html5?", r"css3?", r"tailwind"],
    "Frontend (any)": [r"front-?end"],
    "Mobile": [r"android", r"ios", r"mobile", r"flutter", r"react native"],
    # Data
    "SQL": [r"sql", r"t-sql", r"pl/sql"],
    "PostgreSQL": [r"postgres", r"postgresql"],
    "MySQL": [r"mysql", r"mariadb"],
    "MongoDB": [r"mongodb", r"mongo"],
    "Redis": [r"redis"],
    "NoSQL": [r"nosql", r"dynamodb", r"cassandra"],
    "Elasticsearch": [r"elasticsearch", r"opensearch"],
    "ORM": [r"orm", r"sqlalchemy", r"hibernate"],
    "Spark/Hadoop": [r"spark", r"pyspark", r"hadoop"],
    "Airflow": [r"airflow"],
    "dbt": [r"dbt"],
    "Snowflake": [r"snowflake"],
    "Databricks": [r"databricks"],
    "ETL/data pipelines": [r"etl", r"elt", r"data pipelines?"],
    "Pandas/NumPy": [r"pandas", r"numpy"],
    "Data analysis": [r"data analysis", r"analytics", r"power bi", r"tableau", r"looker", r"bi"],
    "Statistics": [r"statistics", r"statistical", r"data science"],
    "Excel": [r"excel"],
    "Kafka/queues": [r"kafka", r"rabbitmq", r"message queues?", r"event-driven"],
    # Infrastructure
    "Docker": [r"docker", r"containers?", r"containeri[sz]ation", r"podman"],
    "Kubernetes": [r"kubernetes", r"k8s", r"helm", r"openshift"],
    "Linux": [r"linux", r"bash", r"shell", r"unix", r"ubuntu", r"debian"],
    "CI/CD": [r"ci/cd", r"ci", r"continuous integration", r"github actions", r"gitlab ci", r"jenkins"],
    "Git": [r"git", r"version control"],
    "AWS": [r"aws", r"amazon web services", r"lambda", r"ec2", r"s3"],
    "Azure": [r"azure"],
    "GCP": [r"gcp", r"google cloud"],
    "Cloud (any)": [r"cloud"],
    "Terraform/IaC": [r"terraform", r"ansible", r"pulumi", r"infrastructure as code", r"iac"],
    "Virtualization": [r"kvm", r"qemu", r"openstack", r"vmware", r"virtuali[sz]ation"],
    "Monitoring": [r"monitoring", r"observability", r"prometheus", r"grafana", r"logging"],
    "Networking": [r"networking", r"networks?", r"tcp/ip", r"dns"],
    "Security": [r"security", r"cybersecurity", r"owasp", r"penetration testing"],
    "Distributed systems": [r"distributed systems?", r"scalab\w*", r"high[- ]load"],
    "Microservices": [r"microservices?"],
    "REST API": [r"rest", r"restful", r"apis?", r"web services?"],
    "GraphQL": [r"graphql"],
    "Embedded": [r"embedded", r"firmware", r"microcontrollers?", r"fpga"],
    "Debugging/performance": [r"debugging", r"performance", r"troubleshooting", r"incidents?", r"on-call"],
    # AI
    "Machine learning": [r"machine learning", r"ml", r"deep learning", r"computer vision", r"nlp", r"pytorch",
                         r"tensorflow", r"scikit-learn", r"mlops", r"mlflow", r"kubeflow"],
    "LLM/AI": [r"llms?", r"genai", r"generative ai", r"ai", r"rag", r"prompt engineering", r"langchain", r"openai",
               r"vector db\w*", r"pinecone", r"faiss"],
    "AI coding tools": [r"claude code", r"cursor", r"copilot", r"codex", r"ai coding", r"ai-assisted"],
    # Practices
    # "A/B testing" is analytics and "penetration testing" is security, not software testing
    "Testing": [r"(?<!a/b )(?<!penetration )testing", r"(?<!a/b )tests?", r"pytest", r"test automation", r"qa",
                r"selenium", r"playwright", r"tdd"],
    "Agile/Scrum": [r"agile", r"scrum", r"kanban"],
    "Jira/Confluence": [r"jira", r"confluence"],
    "OOP/design patterns": [r"oop", r"object-oriented", r"design patterns"],
    "Algorithms": [r"algorithms?", r"data structures"],
    "Web scraping": [r"scraping", r"scrapy", r"beautifulsoup", r"crawling"],
    "ERP/SAP": [r"sap", r"erp", r"odoo"],
    "Project management": [r"project management", r"product management", r"stakeholders?"],
    "Domain knowledge": [r"domain", r"industry", r"e-?commerce", r"fintech", r"insurance", r"banking",
                         r"healthcare", r"payments?", r"trading", r"quantitative", r"forex", r"crypto", r"finance",
                         r"financial", r"games?", r"gaming"],
    "Soft skills": [r"communication", r"teamwork", r"leadership", r"mentoring"],
    # Not technical
    "Experience 2+ years": [r"(?:[2-9]|1\d)\+?\s*(?:years?|yrs)", r"(?:[2-9]|1\d)\s*-\s*\d+\s*years?", r"senior",
                            r"mid-level", r"staff", r"principal", r"commercial(?:\s+\w+){0,3}\s+experience",
                            r"professional experience"],
    "Czech": [r"czech", r"čeština", r"češtin\w*", r"český"],
    "German": [r"german", r"deutsch"],
    "Other languages": [r"french", r"spanish", r"polish", r"slovak", r"italian", r"dutch", r"hungarian"],
    "English C1+": [r"c1", r"c2", r"native english", r"fluent english"],
    "Degree": [r"degree", r"bachelor'?s?", r"master'?s degree", r"msc", r"bsc", r"phd", r"university"],
}

# Whole words: "C#" is not "C", ".NET" and "C++" are found
_PATTERNS = {name: re.compile(r"(?<![\w#+.])(?:" + "|".join(aliases) + r")(?![\w#+])", re.IGNORECASE)
             for name, aliases in REQUIREMENTS.items()}


def find(text: str) -> set[str]:
    """Requirements mentioned in a text."""
    return {name for name, pattern in _PATTERNS.items() if pattern.search(text)}


def mentions(name: str, text: str) -> int:
    """How many times a requirement from the dictionary is written in a text."""
    return len(_PATTERNS[name].findall(text))


@dataclass
class Insights:
    total: int                            # evaluated jobs counted
    missing: list[tuple[str, int]]        # (requirement, jobs where the model listed it under Missing)
    required: list[tuple[str, int, int]]  # (requirement, jobs that ask for it, of them counted as yours)
    in_cv: set[str]                       # requirements found in the CV Skills section
    unknown: int                          # "missing" items that match no requirement


def _top(counter: Counter) -> list[tuple[str, int]]:
    """Most frequent first, ties by name; the first TOP."""
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:TOP]


def analyze(evaluations: list[dict], cv_skill_lines: list[str]) -> Insights:
    """Count requirements over the model's have / missing lists; each job gives a requirement at most one point."""
    in_cv = set().union(*(find(line) for line in cv_skill_lines))
    missing, required, yours = Counter(), Counter(), Counter()
    unknown = 0
    for evaluation in evaluations:
        lacking = set()
        for item in evaluation.get("missing") or []:
            found = find(item)
            lacking |= found
            unknown += not found
        having = set().union(*(find(item) for item in evaluation.get("have") or []))
        missing.update(lacking - in_cv)  # what the CV already lists is a lack of experience, not a gap
        required.update(lacking | having)
        yours.update(having)
    return Insights(total=len(evaluations), missing=_top(missing),
                    required=[(name, count, yours[name]) for name, count in _top(required)],
                    in_cv=in_cv, unknown=unknown)

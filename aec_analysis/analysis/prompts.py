"""Prompts, schemas, and category definitions for LLM extraction."""

EXTRACTION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "thread_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "extractions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "thread_id": {"type": "string"},
                            "category": {
                                "type": "string",
                                "enum": [
                                    "mobile_tablet", "ai_automation", "collaboration",
                                    "markup_annotation", "measurement_takeoff",
                                    "document_management", "reporting_dashboards",
                                    "integrations", "cloud_web", "performance",
                                    "permissions_security", "scheduling", "cost_financial",
                                    "rfi_submittals", "punch_list_qa", "bim_3d",
                                    "forms_data", "notifications_workflow",
                                    "ux_usability", "training_onboarding",
                                ],
                            },
                            "sentiment": {
                                "type": "string",
                                "enum": ["positive", "negative", "neutral", "mixed"],
                            },
                            "need": {"type": "string"},
                            "severity": {"type": "integer"},
                            "staff_response": {"type": "boolean"},
                            "user_agreement": {"type": "integer"},
                        },
                        "required": [
                            "thread_id", "category", "sentiment", "need",
                            "severity", "staff_response", "user_agreement",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["extractions"],
            "additionalProperties": False,
        },
    },
}

SYSTEM_PROMPT = """You are a product analyst specializing in AEC (Architecture, Engineering & Construction) software. You analyze community forum threads (posts + replies) to extract structured product intelligence.

OUTPUT FORMAT: Respond with ONLY valid JSON. No markdown, no explanation, no thinking tags, no code fences.

FEATURE CATEGORIES (use exactly these labels):
- mobile_tablet: Mobile apps, iPad, field use, offline access
- ai_automation: AI features, auto-detection, OCR, smart tools
- collaboration: Real-time sessions, multi-user, sharing, sync, permissions
- markup_annotation: Drawing markups, stamps, clouds, callouts, redlining
- measurement_takeoff: Measurements, quantities, area calculations, estimation
- document_management: File organization, versioning, search, folders, naming
- reporting_dashboards: Reports, analytics, data export, dashboards
- integrations: Third-party connections (Revit, Excel, Procore, etc.), API, plugins
- cloud_web: Cloud access, web apps, browser-based, SaaS, remote
- performance: Speed, crashes, freezing, memory, loading times
- permissions_security: User roles, access control, security, admin
- scheduling: Timelines, Gantt charts, calendars, deadlines, milestones
- cost_financial: Budgets, invoicing, change orders, cost tracking, billing
- rfi_submittals: RFIs, submittals, transmittals, approval workflows
- punch_list_qa: Punch lists, inspections, quality, safety, checklists
- bim_3d: BIM coordination, 3D models, Revit, Navisworks, IFC
- forms_data: Custom forms, fillable PDFs, data capture, templates
- notifications_workflow: Alerts, automated workflows, approval chains, triggers
- ux_usability: UI complaints, confusing workflows, workarounds, ease of use
- training_onboarding: Learning resources, documentation, tutorials, certification

SENTIMENT:
- positive: User praises, loves, recommends, or thanks
- negative: User complains, reports bugs, expresses frustration
- neutral: User asks a question or makes a suggestion without strong emotion
- mixed: Thread contains both positive and negative sentiment

/no_think"""

EXTRACTION_PROMPT = """Analyze these {platform} community forum threads. For each thread, extract:

1. category: The primary feature category from the list in your instructions
2. sentiment: positive, negative, neutral, or mixed
3. need: The core user need or issue in under 20 words
4. severity: 1-5 (5=critical blocker, 4=major pain, 3=moderate, 2=minor, 1=nice-to-have)
5. staff_response: true if staff/official replied, false otherwise
6. user_agreement: number of users in thread who expressed the same need

{threads_text}

Respond with ONLY a JSON array. One object per thread:
[{{"thread_id": "ID", "category": "...", "sentiment": "...", "need": "...", "severity": 3, "staff_response": false, "user_agreement": 1}}]"""

CATEGORY_LABELS = {
    "mobile_tablet": "Mobile & Tablet",
    "ai_automation": "AI & Automation",
    "collaboration": "Collaboration",
    "markup_annotation": "Markup & Annotation",
    "measurement_takeoff": "Measurement & Takeoff",
    "document_management": "Document Management",
    "reporting_dashboards": "Reporting & Dashboards",
    "integrations": "Integrations",
    "cloud_web": "Cloud & Web Access",
    "performance": "Performance",
    "permissions_security": "Permissions & Security",
    "scheduling": "Scheduling",
    "cost_financial": "Cost & Financial",
    "rfi_submittals": "RFI & Submittals",
    "punch_list_qa": "Punch List & QA",
    "bim_3d": "BIM & 3D",
    "forms_data": "Forms & Data Capture",
    "notifications_workflow": "Notifications & Workflow",
    "ux_usability": "UX & Usability",
    "training_onboarding": "Training & Onboarding",
}

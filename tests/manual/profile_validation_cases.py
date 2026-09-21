TEST_CASES = [
    {
        "name": "VAL-001: valid single requirement",
        "expected_valid": True,
        "expected_codes": [],
        "payload": {
            "request_id": "VAL-001",
            "project_name": "Python Automation Tool",
            "project_description": (
                "Students must build an automation tool using Python."
            ),
            "project_summary": "Build a Python automation tool.",
            "requirements": [
                {
                    "skill_id": "python",
                    "canonical_name": "Python",
                    "importance": "hard_requirement",
                    "required_level": 2,
                    "evidence_text": "using Python",
                    "confidence": 0.97,
                    "decision_basis": "Python is explicitly required.",
                    "provenance": [
                        {
                            "source_requirement_index": 0,
                            "raw_skill": "Python",
                            "importance": "hard_requirement",
                            "required_level": 2,
                            "evidence_text": "using Python",
                            "extraction_decision_basis": (
                                "Python is explicitly required."
                            ),
                            "extraction_confidence": 0.97,
                            "match_method": "exact",
                            "taxonomy_decision_basis": (
                                "Python exactly matches the taxonomy."
                            ),
                        }
                    ],
                }
            ],
            "unresolved_skills": [],
            "unresolved_requirements": [],
        },
    },
    {
        "name": "VAL-002: warning-only low confidence",
        "expected_valid": True,
        "expected_codes": [
            "LOW_EXTRACTION_CONFIDENCE",
        ],
        "payload": {
            "request_id": "VAL-002",
            "project_name": "Python Data Tool",
            "project_description": (
                "Python experience may be useful for developing the tool."
            ),
            "project_summary": "Develop a small data tool.",
            "requirements": [
                {
                    "skill_id": "python",
                    "canonical_name": "Python",
                    "importance": "preferred",
                    "required_level": 1,
                    "evidence_text": "Python experience may be useful",
                    "confidence": 0.55,
                    "decision_basis": (
                        "Python is described as useful rather than mandatory."
                    ),
                    "provenance": [
                        {
                            "source_requirement_index": 0,
                            "raw_skill": "Python",
                            "importance": "preferred",
                            "required_level": 1,
                            "evidence_text": ("Python experience may be useful"),
                            "extraction_decision_basis": (
                                "Python is useful but optional."
                            ),
                            "extraction_confidence": 0.55,
                            "match_method": "exact",
                            "taxonomy_decision_basis": (
                                "Python exactly matches the taxonomy."
                            ),
                        }
                    ],
                }
            ],
            "unresolved_skills": [],
            "unresolved_requirements": [],
        },
    },
    {
        "name": "VAL-003: hard requirement missing level",
        "expected_valid": False,
        "expected_codes": [
            "MISSING_REQUIRED_LEVEL",
        ],
        "payload": {
            "request_id": "VAL-003",
            "project_name": "Python API",
            "project_description": "Python is required to build the API.",
            "project_summary": "Build a Python API.",
            "requirements": [
                {
                    "skill_id": "python",
                    "canonical_name": "Python",
                    "importance": "hard_requirement",
                    "required_level": None,
                    "evidence_text": "Python is required",
                    "confidence": 0.98,
                    "decision_basis": "Python is mandatory.",
                    "provenance": [
                        {
                            "source_requirement_index": 0,
                            "raw_skill": "Python",
                            "importance": "hard_requirement",
                            "required_level": None,
                            "evidence_text": "Python is required",
                            "extraction_decision_basis": ("Python is mandatory."),
                            "extraction_confidence": 0.98,
                            "match_method": "exact",
                            "taxonomy_decision_basis": ("Exact taxonomy match."),
                        }
                    ],
                }
            ],
            "unresolved_skills": [],
            "unresolved_requirements": [],
        },
    },
    {
        "name": "VAL-004: unknown taxonomy skill",
        "expected_valid": False,
        "expected_codes": [
            "UNKNOWN_SKILL_ID",
        ],
        "payload": {
            "request_id": "VAL-004",
            "project_name": "Rust Service",
            "project_description": ("Students must develop the service using Rust."),
            "project_summary": "Develop a service using Rust.",
            "requirements": [
                {
                    "skill_id": "rust-programming",
                    "canonical_name": "Rust",
                    "importance": "hard_requirement",
                    "required_level": 2,
                    "evidence_text": "using Rust",
                    "confidence": 0.98,
                    "decision_basis": "Rust is explicitly required.",
                    "provenance": [
                        {
                            "source_requirement_index": 0,
                            "raw_skill": "Rust",
                            "importance": "hard_requirement",
                            "required_level": 2,
                            "evidence_text": "using Rust",
                            "extraction_decision_basis": (
                                "Rust is explicitly required."
                            ),
                            "extraction_confidence": 0.98,
                            "match_method": "exact",
                            "taxonomy_decision_basis": (
                                "Test deliberately uses an unknown ID."
                            ),
                        }
                    ],
                }
            ],
            "unresolved_skills": [],
            "unresolved_requirements": [],
        },
    },
    {
        "name": "VAL-005: canonical name mismatch",
        "expected_valid": False,
        "expected_codes": [
            "CANONICAL_NAME_MISMATCH",
        ],
        "payload": {
            "request_id": "VAL-005",
            "project_name": "Python Service",
            "project_description": "Build the service using Python.",
            "project_summary": "Build a Python service.",
            "requirements": [
                {
                    "skill_id": "python",
                    "canonical_name": "Java",
                    "importance": "hard_requirement",
                    "required_level": 2,
                    "evidence_text": "using Python",
                    "confidence": 0.99,
                    "decision_basis": "Python is required.",
                    "provenance": [
                        {
                            "source_requirement_index": 0,
                            "raw_skill": "Python",
                            "importance": "hard_requirement",
                            "required_level": 2,
                            "evidence_text": "using Python",
                            "extraction_decision_basis": ("Python is required."),
                            "extraction_confidence": 0.99,
                            "match_method": "exact",
                            "taxonomy_decision_basis": ("Python matched the taxonomy."),
                        }
                    ],
                }
            ],
            "unresolved_skills": [],
            "unresolved_requirements": [],
        },
    },
    {
        "name": "VAL-006: evidence is not verbatim",
        "expected_valid": False,
        "expected_codes": [
            "EVIDENCE_NOT_VERBATIM",
            "PROVENANCE_EVIDENCE_NOT_VERBATIM",
        ],
        "payload": {
            "request_id": "VAL-006",
            "project_name": "Reporting Application",
            "project_description": ("Build a reporting application using Python."),
            "project_summary": "Build a reporting application.",
            "requirements": [
                {
                    "skill_id": "python",
                    "canonical_name": "Python",
                    "importance": "hard_requirement",
                    "required_level": 2,
                    "evidence_text": ("Advanced Python expertise is mandatory."),
                    "confidence": 0.96,
                    "decision_basis": "Python is required.",
                    "provenance": [
                        {
                            "source_requirement_index": 0,
                            "raw_skill": "Python",
                            "importance": "hard_requirement",
                            "required_level": 2,
                            "evidence_text": (
                                "Advanced Python expertise is mandatory."
                            ),
                            "extraction_decision_basis": ("Python is required."),
                            "extraction_confidence": 0.96,
                            "match_method": "exact",
                            "taxonomy_decision_basis": ("Exact taxonomy match."),
                        }
                    ],
                }
            ],
            "unresolved_skills": [],
            "unresolved_requirements": [],
        },
    },
    {
        "name": "VAL-007: incorrect merged importance and level",
        "expected_valid": False,
        "expected_codes": [
            "PROVENANCE_IMPORTANCE_CONFLICT",
            "PROVENANCE_LEVEL_CONFLICT",
        ],
        "payload": {
            "request_id": "VAL-007",
            "project_name": "Python Optimization",
            "project_description": (
                "Python experience is preferred. "
                "Advanced Python is required for optimization."
            ),
            "project_summary": "Optimize a service using Python.",
            "requirements": [
                {
                    "skill_id": "python",
                    "canonical_name": "Python",
                    "importance": "preferred",
                    "required_level": 1,
                    "evidence_text": "Python experience is preferred.",
                    "confidence": 0.90,
                    "decision_basis": "Python is preferred.",
                    "provenance": [
                        {
                            "source_requirement_index": 0,
                            "raw_skill": "Python",
                            "importance": "preferred",
                            "required_level": 1,
                            "evidence_text": ("Python experience is preferred."),
                            "extraction_decision_basis": (
                                "Basic Python experience is preferred."
                            ),
                            "extraction_confidence": 0.90,
                            "match_method": "exact",
                            "taxonomy_decision_basis": ("Exact taxonomy match."),
                        },
                        {
                            "source_requirement_index": 1,
                            "raw_skill": "Advanced Python",
                            "importance": "hard_requirement",
                            "required_level": 3,
                            "evidence_text": (
                                "Advanced Python is required for optimization."
                            ),
                            "extraction_decision_basis": (
                                "Advanced Python is mandatory."
                            ),
                            "extraction_confidence": 0.98,
                            "match_method": "alias",
                            "taxonomy_decision_basis": (
                                "Advanced Python maps to Python."
                            ),
                        },
                    ],
                }
            ],
            "unresolved_skills": [],
            "unresolved_requirements": [],
        },
    },
    {
        "name": "VAL-008: unmapped requirement",
        "expected_valid": False,
        "expected_codes": [
            "UNMAPPED_REQUIREMENT",
        ],
        "payload": {
            "request_id": "VAL-008",
            "project_name": "Service Optimization",
            "project_description": (
                "Python is required. Students must optimize service performance."
            ),
            "project_summary": "Optimize a Python service.",
            "requirements": [
                {
                    "skill_id": "python",
                    "canonical_name": "Python",
                    "importance": "hard_requirement",
                    "required_level": 2,
                    "evidence_text": "Python is required.",
                    "confidence": 0.99,
                    "decision_basis": "Python is mandatory.",
                    "provenance": [
                        {
                            "source_requirement_index": 0,
                            "raw_skill": "Python",
                            "importance": "hard_requirement",
                            "required_level": 2,
                            "evidence_text": "Python is required.",
                            "extraction_decision_basis": ("Python is mandatory."),
                            "extraction_confidence": 0.99,
                            "match_method": "exact",
                            "taxonomy_decision_basis": ("Exact taxonomy match."),
                        }
                    ],
                }
            ],
            "unresolved_skills": [
                "Performance Optimization",
            ],
            "unresolved_requirements": [
                {
                    "source_requirement_index": 1,
                    "raw_skill": "Performance Optimization",
                    "mapping_status": "unmapped",
                    "importance": "hard_requirement",
                    "required_level": 3,
                    "evidence_text": ("Students must optimize service performance."),
                    "candidate_skill_ids": [],
                }
            ],
        },
    },
    {
        "name": "VAL-009: needs-review requirement",
        "expected_valid": False,
        "expected_codes": [
            "NEEDS_REVIEW_REQUIREMENT",
        ],
        "payload": {
            "request_id": "VAL-009",
            "project_name": "Cloud Deployment",
            "project_description": (
                "Python is required. The application may be deployed to AWS or Azure."
            ),
            "project_summary": "Build and deploy a Python application.",
            "requirements": [
                {
                    "skill_id": "python",
                    "canonical_name": "Python",
                    "importance": "hard_requirement",
                    "required_level": 2,
                    "evidence_text": "Python is required.",
                    "confidence": 0.99,
                    "decision_basis": "Python is mandatory.",
                    "provenance": [
                        {
                            "source_requirement_index": 0,
                            "raw_skill": "Python",
                            "importance": "hard_requirement",
                            "required_level": 2,
                            "evidence_text": "Python is required.",
                            "extraction_decision_basis": ("Python is mandatory."),
                            "extraction_confidence": 0.99,
                            "match_method": "exact",
                            "taxonomy_decision_basis": ("Exact taxonomy match."),
                        }
                    ],
                }
            ],
            "unresolved_skills": [
                "AWS or Azure",
            ],
            "unresolved_requirements": [
                {
                    "source_requirement_index": 1,
                    "raw_skill": "AWS or Azure",
                    "mapping_status": "needs_review",
                    "importance": "preferred",
                    "required_level": 1,
                    "evidence_text": "deployed to AWS or Azure",
                    "candidate_skill_ids": [
                        "aws",
                        "gcp-azure",
                    ],
                }
            ],
        },
    },
    {
        "name": "VAL-010: multiple issues returned together",
        "expected_valid": False,
        "expected_codes": [
            "CANONICAL_NAME_MISMATCH",
            "MISSING_REQUIRED_LEVEL",
            "EMPTY_PROVENANCE",
            "LOW_EXTRACTION_CONFIDENCE",
            "EVIDENCE_NOT_VERBATIM",
        ],
        "payload": {
            "request_id": "VAL-010",
            "project_name": "Broken Test Profile",
            "project_description": ("Build an application using Python."),
            "project_summary": "Build an application.",
            "requirements": [
                {
                    "skill_id": "python",
                    "canonical_name": "Java",
                    "importance": "hard_requirement",
                    "required_level": None,
                    "evidence_text": ("Advanced Python is mandatory."),
                    "confidence": 0.40,
                    "decision_basis": ("Deliberately invalid test data."),
                    "provenance": [],
                }
            ],
            "unresolved_skills": [],
            "unresolved_requirements": [],
        },
    },
]

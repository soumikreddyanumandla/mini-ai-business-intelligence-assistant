# Architecture & Data-Flow Diagrams – Mini AI BI Assistant

This document contains comprehensive visual architecture and data-flow diagrams illustrating the system's operational architecture, defensive security perimeter, analytics pipelines, and cloud migration path.

---

## 1. End-to-End Conversational Query & Grounding Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as Business User / Analyst
    participant UI as Streamlit Frontend (Port 8501)
    participant RateLimiter as In-Memory Rate Limiter
    participant RBAC as RBAC Guard (X-User-Role)
    participant Guard as Prompt Injection Guard (Step 0)
    participant AI as AI Intent Router (Gemini / Fallback)
    participant Registry as Tool Registry Allowlist
    participant Cache as In-Memory Analytics Cache
    participant DB as SQLite WAL Database

    User->>UI: Enters "What is the total revenue?"
    UI->>RateLimiter: POST /api/ask {question, session_id}
    Note over RateLimiter: Sliding window check (<= 60 req/min)
    RateLimiter->>RBAC: Request allowed
    Note over RBAC: Checks role in ['Admin', 'Analyst']
    RBAC->>Guard: Authorized request
    Note over Guard: Regex & delimiter scan against adversarial patterns
    Guard->>AI: Clean sanitized query
    
    alt Gemini API Verified Operational
        AI->>AI: Gemini Structured Output classifies Intent & Parameters
    else Gemini Offline / Timeout / Quota Exhaustion
        AI->>AI: Deterministic Regex Pattern Intent Router (Zero-Downtime Fallback)
    end

    AI->>Registry: Lookup tool "total_revenue"
    Registry->>Cache: Query cache check key "analytics:get_total_revenue"
    
    alt Cache Hit
        Cache-->>Registry: Return cached metrics dict
    else Cache Miss
        Registry->>DB: Execute parameterized ORM aggregation (SELECT SUM(net_revenue) WHERE is_eligible = 1)
        DB-->>Registry: Return exact numerical aggregates
        Registry->>Cache: Store result in cache (TTL = 60s)
    end

    Registry-->>AI: Verified metrics + row provenance counts
    AI->>AI: Format grounded headline answer + build provenance card
    AI-->>UI: Return QueryResponse JSON (Category 1, Metrics, Provenance)
    UI-->>User: Render Metric Cards, Dynamic Chart, and Expandable Provenance Box
```

---

## 2. Multi-Layer Security & Defensive Perimeter (Package A)

```mermaid
graph TD
    ClientReq[Incoming HTTP Request] --> L1{Layer 1: IP Rate Limiting}
    L1 -->|Exceeded > 60/min| Err429[HTTP 429: Too Many Requests]
    L1 -->|Pass| L2{Layer 2: RBAC Authorization}
    
    L2 -->|Role Forbidden| Err403[HTTP 403: Forbidden]
    L2 -->|Authorized| L3{Layer 3: Step 0 Prompt Injection Guard}
    
    L3 -->|Adversarial Pattern Detected| SecAudit[Write to SecurityAuditLog]
    SecAudit --> BlockResp[Category 4: Security Guardrail Violation Response]
    
    L3 -->|Clean Business Query| L4{Layer 4: Tool Allowlist Enforcement}
    L4 -->|Tool in Allowlist| Exec[Parameterized SQLite Query Execution]
    L4 -->|Unregistered Tool| ErrTool[Tool Execution Blocked]
    
    Exec --> L5{Layer 5: Output Sanitization}
    L5 -->|CSV Spreadsheet Export| CSVFilter[CSV Formula Sanitization: Neutralize = + - @ \t \r]
    L5 -->|JSON API Response| ProvAttach[Attach Operational Provenance Metadata]
    
    CSVFilter --> ClientOut[Secure Client Delivery]
    ProvAttach --> ClientOut
```

---

## 3. Atomic CSV Ingestion, Profiling & Cache Invalidation (Package C)

```mermaid
flowchart TD
    Upload[Admin uploads Sales CSV] --> Rate[Upload Rate Limiter: <= 10/min]
    Rate --> SaveTemp[Save file to isolated scratch/ directory]
    SaveTemp --> Profile[Automated Column Profiling: Inferred Types, Nulls, Card, Bounds]
    Profile --> QualityCheck[Compute Multi-Dimensional Data Quality Index (DQI)]
    
    subgraph DQI 5-Dimension Evaluation
        QualityCheck --> D1[Completeness: 25%]
        QualityCheck --> D2[Validity: 25%]
        QualityCheck --> D3[Consistency: 20%]
        QualityCheck --> D4[Uniqueness: 15%]
        QualityCheck --> D5[Timeliness: 15%]
    end

    QualityCheck --> StageDB[Stage Records in Pending SQLite Transaction]
    
    alt Schema or Critical Validation Error
        StageDB --> Rollback[Atomic Rollback: Existing Dataset Completely Preserved]
        Rollback --> ErrorResponse[HTTP 422: Ingestion Rejected]
    else Validation Successful
        StageDB --> Commit[Commit Transaction: Sync to sales_transactions table]
        Commit --> AuditLog[Write Import Lineage to data_quality_logs]
        AuditLog --> Invalidate[Atomic Analytics Cache Invalidation: Flush analytics_cache]
        Invalidate --> SuccessResponse[HTTP 200: Successfully Synced Dataset]
    end
```

---

## 4. Advanced Analytics & Quota Pacing Architecture (Package B)

```mermaid
graph LR
    subgraph Input Dataset
        DB[(Audited SQLite Transactions)]
    end

    subgraph Package B Analytical Engines
        DB --> Anom[Anomaly Detection Engine]
        DB --> Pareto[Pareto 80/20 Engine]
        DB --> WhatIf[What-If Simulation Engine]
        DB --> Quota[Sales Target Pacing Engine]
    end

    subgraph Analytical Outputs & Governance Guarantees
        Anom --> AnomOut[Separates Statistical Outliers (IQR/Z-score) from Data Quality Errors]
        Pareto --> ParetoOut[Identifies Vital Few Products with Audited Realized Denominator]
        WhatIf --> WhatIfOut[Models Price/Volume/Discount Deltas without Inventing Cost Data]
        Quota --> QuotaOut[Evaluates Run-Rate Attainment vs Configured Targets]
    end
```

---

## 5. Enterprise AWS Cloud Migration Architecture

```mermaid
graph TD
    subgraph User Access
        Browser[Corporate Analyst Web Browser]
    end

    subgraph AWS Ingestion & Security Perimeter
        Route53[Amazon Route 53 DNS] --> CloudFront[Amazon CloudFront CDN + AWS WAF]
        CloudFront --> ALB[Application Load Balancer]
        ALB --> ECSStreamlit[Streamlit UI Container on AWS Fargate]
        ALB --> ECSFastAPI[FastAPI Backend Container on AWS Fargate]
    end

    subgraph AWS Data & Persistence Tier
        ECSFastAPI --> AuroraPostgres[(Amazon Aurora Serverless PostgreSQL Multi-AZ)]
        ECSFastAPI --> ElastiCache[(Amazon ElastiCache Redis Cluster)]
        S3Bucket[(Amazon S3 Data Lake Bucket)] --> LambdaIngest[AWS Lambda Ingestion Trigger]
        LambdaIngest --> AuroraPostgres
    end

    subgraph AWS GenAI & Cloud Intelligence
        ECSFastAPI --> Bedrock[Amazon Bedrock Claude 3.5 Sonnet / Llama 3]
        ECSFastAPI --> SecretsManager[AWS Secrets Manager: Centralized Key Vault]
        ECSFastAPI --> CloudWatch[Amazon CloudWatch Metrics & Alarms]
    end

    Browser --> Route53
```

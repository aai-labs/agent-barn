# Merkys read-only endpoint reference

Condensed from Merkys's OpenAPI document for use with `aai-cli merkys request GET <path>`. Use the dedicated commands (`ask`, `research`, `conversations`, `documents`, `sources`, `assistants`) first; use these endpoints for everything else.

All paths are relative to the profile's `base_url`. Auth (`X-API-Key`) is added for you. Every call is scoped to the API key owner's organization and access rights: an empty list or a 403 can mean the key owner lacks the role or ACL, not that the data is missing.
Pass query parameters with `--query key=value` (repeat for more). `request` is read-only unless `--allow-write` is set; do not use `--allow-write` for knowledge lookups.

Notation: `*` = required parameter.

## Conversations (user-scoped)

- `GET /api/conversation/search` — Search Conversations
  - params: `q*` (query, string), `limit` (query, integer), `page_token` (query, string)
- `GET /api/conversation/{conversation_id}/messages` — Get Conversation Messages
  - params: `conversation_id*` (path, string), `limit` (query, integer), `page_token` (query, string)
- `GET /api/conversation/` — Get Conversations
  - params: `limit` (query, integer), `page_token` (query, string)
- `GET /api/conversation/organization-chats` — Get Organization Conversations
  - params: `limit` (query, integer), `page_token` (query, string)

## Documents

- `GET /api/documents` — Get Documents. Get list of uploaded documents for the authenticated user's organization
  - params: `limit` (query, integer)
  - returns: `[DocumentResponse]`
- `GET /api/documents/{document_id}/content` — Get Document Content. Get the content of a specific document by ID
  - params: `document_id*` (path, string)

## Data sources and indexed resources

- `GET /api/sources/` — List Data Sources
  - params: `limit` (query, integer), `offset` (query, integer)
- `GET /api/sources/{data_source_id}` — Get Data Source
  - params: `data_source_id*` (path, string)
- `GET /api/sources/coverage` — Get Coverage
  - returns: `CoverageReportDTO`
- `GET /api/sources/{data_source_id}/resources/{resource_type}` — List Resources
  - params: `data_source_id*` (path, string), `resource_type*` (path, string), `parent_id` (query, string), `limit` (query, integer), `offset` (query, integer)
- `GET /api/sources/{data_source_id}/resources/{resource_type}/{resource_id}` — Get Resource
  - params: `data_source_id*` (path, string), `resource_type*` (path, string), `resource_id*` (path, string)

## Custom assistants

- `GET /api/custom-assistants/` — List Assistants
  - returns: `[CustomAssistantResponseDTO]`
- `GET /api/custom-assistants/{assistant_id}` — Get Assistant
  - params: `assistant_id*` (path, string)
  - returns: `CustomAssistantResponseDTO`

## Legal corpus (Merkys Law)

- `GET /v1/legal-corpus/practice` — Get Norm Practice. How courts have applied one article.
  - params: `norm_key*` (query, string), `limit` (query, integer), `offset` (query, integer)
  - returns: `NormPracticeDTO`
- `GET /v1/legal-corpus/upcoming` — List Upcoming Laws
  - params: `horizon_days` (query, integer), `issuing_body` (query, string), `authority` (query, string), `document_type` (query, string)
  - returns: `[UpcomingLawDTO]`
- `GET /v1/legal-corpus/regulatory/stats` — Get Regulatory Stats
  - returns: `RegulatoryStatsDTO`
- `GET /v1/legal-corpus/regulatory/upcoming` — List Regulatory Upcoming Laws
  - params: `horizon_days` (query, integer)
  - returns: `[UpcomingLawDTO]`
- `GET /v1/legal-corpus/regulatory/laws` — List Regulatory Laws
  - params: `status` (query, one of all/in_force/upcoming/superseded), `issuing_body` (query, string), `document_type` (query, string), `q` (query, string), `limit` (query, integer), `offset` (query, integer)
  - returns: `RegulatoryLawsDTO`
- `GET /v1/legal-corpus/regulatory/filter-options` — Get Regulatory Filter Options
  - returns: `RegulatoryFilterOptionsDTO`

## EU case law

- `GET /v1/eu-case-law/resolve` — Resolve Case
  - params: `case_number*` (query, string)
  - returns: `ResolveResponse`
- `GET /v1/eu-case-law/tracked` — List Tracked
  - returns: `[IngestionResponse]`

## Law commentary

- `GET /v1/law-commentary/stats` — Commentary Stats
  - returns: `CommentaryStatsResponse`
- `GET /v1/law-commentary/pages` — Commentary Pages
  - params: `chapter` (query, string), `kind` (query, string), `q` (query, string), `limit` (query, integer), `offset` (query, integer)
  - returns: `CommentaryPagesResponse`
- `GET /v1/law-commentary/filter-options` — Commentary Filter Options
  - returns: `CommentaryFilterOptions`

## Medical corpus

- `GET /v1/medical-corpus/stats` — Get Medical Corpus Stats
  - returns: `MedicalCorpusStatsDTO`
- `GET /v1/medical-corpus/documents` — List Medical Documents
  - params: `source` (query, string), `description_kind` (query, string), `collection` (query, string), `domain` (query, string), `staleness` (query, string), `q` (query, string), `limit` (query, integer), `offset` (query, integer)
  - returns: `MedicalDocumentsDTO`
- `GET /v1/medical-corpus/documents/{document_id}` — Get Medical Document
  - params: `document_id*` (path, string)
  - returns: `MedicalDocumentDetailDTO`
- `GET /v1/medical-corpus/filter-options` — Get Medical Filter Options
  - returns: `MedicalFilterOptionsDTO`

## Corpus provenance

- `GET /v1/corpus-provenance/{corpus}` — Get Corpus Provenance
  - params: `corpus*` (path, string), `q` (query, string), `group` (query, string), `authority` (query, string), `document_type` (query, string), `status` (query, string), `feed` (query, string), `domain` (query, string), `freshness` (query, string), `limit` (query, integer), `offset` (query, integer)
  - returns: `CorpusProvenanceDTO`
- `GET /v1/corpus-provenance/{corpus}/documents/{document_id}` — Get Corpus Document
  - params: `corpus*` (path, string), `document_id*` (path, string)
  - returns: `CorpusDocumentDetailDTO`

## Statistics (GET)

- `GET /api/statistics/faithfulness-ranking` — Get Faithfulness Ranking
  - params: `page` (query, integer), `page_size` (query, integer), `start_date` (query, string), `end_date` (query, string), `sort_dir` (query, one of asc/desc), `min_score` (query, number), `max_score` (query, number)
  - returns: `FaithfulnessRankingResponse`
- `GET /api/statistics/negative-feedback-tags` — Get Negative Feedback Tags
  - params: `timeframe` (query, one of daily/weekly/monthly), `timeframe_count` (query, integer), `start_date` (query, string), `end_date` (query, string)
  - returns: `NegativeFeedbackTagsResponse`
- `GET /api/statistics/feedback-breakdown` — Get Feedback Breakdown
  - params: `start_date` (query, string), `end_date` (query, string)
  - returns: `FeedbackBreakdownResponse`
- `GET /api/statistics/feedback-by-tool` — Get positive and negative feedback counts by answer tool
  - params: `start_date` (query, string), `end_date` (query, string)
  - returns: `FeedbackByToolResponse`
- `GET /api/statistics/abstention-trends` — Get Abstention Trends
  - params: `timeframe` (query, one of daily/weekly/monthly), `timeframe_count` (query, integer), `start_date` (query, string), `end_date` (query, string)
  - returns: `AbstentionTrendsResponse`
- `GET /api/statistics/factuality-trends` — Get Factuality Trends
  - params: `timeframe` (query, one of daily/weekly/monthly), `timeframe_count` (query, integer), `start_date` (query, string), `end_date` (query, string)
  - returns: `FactualityTrendsResponse`

## Service

- `GET /api/limits` — Get Limits. Return client-facing upload/text limits.
  - returns: `UploadLimits`
- `GET /healthz` — Health Check

# SKKU Course Agent MVP Architecture

## Boundaries

- `apps/frontend`: Next.js TypeScript web app for students, instructors, and admins.
- `apps/backend`: FastAPI application that owns authentication, REST APIs, database access, uploads, and service orchestration.
- `packages/ai_rag`: Python package for document chunking, embeddings, vector search, retrieval, and answer generation.
- `packages/shared`: TypeScript and JSON Schema contracts shared by frontend and API clients.
- `infra`: local infrastructure definitions such as PostgreSQL and pgvector initialization.

## MVP Flow

1. Instructor uploads a course material through the backend.
2. Backend stores file metadata in PostgreSQL and queues ingestion.
3. AI/RAG module extracts text, splits chunks, creates embeddings, and stores searchable vectors.
4. Student selects a course and asks a question.
5. Backend restricts retrieval to the selected course, asks the RAG module for relevant chunks, calls the LLM, and returns citations.
6. Backend writes chat logs and citation metadata for audit and statistics.

## Data Ownership

- PostgreSQL is the source of truth for users, courses, materials, chat sessions, and logs.
- pgvector can live in the same PostgreSQL instance for MVP simplicity.
- Object storage can start as a local `uploads/` folder and later move to S3-compatible storage without changing public API contracts.

## Future Split Points

- Move `packages/ai_rag` behind a worker queue when ingestion becomes slow.
- Replace in-process RAG calls with a separate AI service if GPU, batch, or data governance needs grow.
- Generate OpenAPI/TypeScript clients from FastAPI once endpoint behavior stabilizes.

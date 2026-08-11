"""COURSE AGENT integrated into the SKKU Course Agent backend.

The voice agent keeps its own Grok realtime transport, weak-concept memory and
trusted-web fallback, but every retrieval is course-scoped through the existing
``RagService`` so professors keep managing materials in one place. All xAI and
Moss configuration lives in ``app.core.config.Settings`` rather than in a second
dotenv loader.
"""

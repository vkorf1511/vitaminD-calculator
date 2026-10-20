## IMPLEMENTATION TECHNOLOGIES
- Backend: Python with FastAPI
- Frontend: React with Next.js
- QA: 
-- FE: Playwright
-- BE: pytest 
-- e2e: Playwright
- Container: Docker images, two in number one for optimized for Azure and the other for AWS. You must create the necessary infrastructure to create the container images of the microservice, thus dockerfiles, dockerignore and anything else that you might think is needed.
- CI/CD: standard GitHub Actions workflow file (.github/workflows/ci.yml) to test your FastAPI app using pytest
- Logging: check dedicated section below called 'Logging Requirements'
- Metrics: prometheus-fastapi-instrumentator exposed in '/metrics' endpoint to track latency, number of requests and any other industry standards that you might find valuable.
- **Distributed Tracing:** Implement OpenTelemetry instrumentation for FastAPI and `httpx` (or `requests`) so that outgoing third-party API calls inherit trace context headers.


## SDLC extra DETAILS:
- **Specifications:** I want you to first create an OpenAPI spec, in yaml and save it in the project's root folder under the name "openAPI-specs".
- **Tests:** aim for for 85% coverage
-- Unit tests
-- Integration tests
-- e2e tests
- **Error Handling:** Ensure unhandled exceptions are caught, logged with full stack traces, and return a clean, user-friendly JSON error response to the frontend GUI.
- ** Documentation:** Leverage OpenApi specs and what you know here to provide the official api documentation for all microservices (the main one, and any other that you might create). Also provide user journeys of the standard user flows.

## Logging Requirements
- **Format:** Structured JSON logging to `stdout`.
- **Library:** Use Python's built-in `logging` module configured with a JSON formatter (or `structlog`).
- **Log Levels:** 
  - `INFO` for successful request flows and third-party call completions.
  - `ERROR` for failed third-party API responses or validation errors.
- **Context:** Every log entry must include a timestamp, log level, message, and a unique request ID to trace the lifecycle of a user action from the GUI to the third-party service and back.
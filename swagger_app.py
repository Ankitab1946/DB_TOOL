from fastapi import FastAPI
from DataDictionaryAdminApp.config import get_settings
from DataDictionaryAdminApp.api.routers import audit, data_dictionary, lookups, master_upload, portfolio_reference, prompts, s3, system

settings = get_settings()
app = FastAPI(
    title="PRJ Data Dictionary Administration API",
    version="2.1.0",
    description="Swagger API for filters, raw/staging operations, finalization, prompt management, audit and S3 export.",
)

for router in [system.router, lookups.router, data_dictionary.router, master_upload.router, prompts.router, audit.router, portfolio_reference.router, s3.router]:
    app.include_router(router, prefix="/api/v1")

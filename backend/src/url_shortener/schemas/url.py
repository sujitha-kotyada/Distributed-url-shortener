from datetime import datetime

from pydantic import AnyUrl, BaseModel, field_validator


class UrlCreateRequest(BaseModel):
    url: AnyUrl

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: AnyUrl) -> AnyUrl:
        if value.scheme not in {"http", "https"}:
            raise ValueError("URL scheme must be http or https.")
        return value


class UrlCreateResponse(BaseModel):
    short_code: str
    short_url: str
    original_url: str
    created_at: datetime

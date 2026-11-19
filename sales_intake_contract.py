"""Shared sales intake wire contract; copied identically into the MCP portal."""
from datetime import date
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SalesDetails(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    customer_id: str = Field(pattern=r'^[0-9]{1,50}$')
    project_name: str = Field(min_length=3, max_length=200)
    project_type: str = Field(min_length=1, max_length=160)
    request_type: Literal['Sold project', 'Trial']
    sales_owner: str = Field(min_length=1, max_length=200)
    scope: str = Field(min_length=10, max_length=10000)
    contact_name: str = Field(min_length=1, max_length=160)
    contact_email: str = Field(pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$', max_length=254)
    contact_phone: str = Field(default='', max_length=80)
    requested_go_live: date | None = None
    go_live_unknown: bool = Field(default=False, strict=True)
    quote_reference: str = Field(default='', max_length=50)
    supporting_links: list[str] = Field(default_factory=list, max_length=5)

    @field_validator('supporting_links')
    @classmethod
    def links(cls, values):
        result = []
        for value in values:
            value = value.strip()
            u = urlsplit(value)
            if len(value) > 2000 or u.scheme != 'https' or not u.hostname or u.username or u.password or any(c.isspace() or ord(c) < 32 for c in value):
                raise ValueError('Supporting documents must use full HTTPS links.')
            result.append(value)
        return result

    @model_validator(mode='after')
    def required_choices(self):
        if bool(self.requested_go_live) == self.go_live_unknown:
            raise ValueError('Provide a requested go-live date or select Unknown.')
        if self.request_type == 'Sold project' and not self.quote_reference:
            raise ValueError('A quote reference is required for a sold project.')
        return self


class SalesForm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    submission_id: UUID
    details: SalesDetails


class SalesSubmitter(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$', max_length=254)


class SalesSubmission(SalesForm):
    submitter: SalesSubmitter

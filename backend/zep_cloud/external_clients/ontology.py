from pydantic import BaseModel, ConfigDict

EntityText = str


class EntityModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class EdgeModel(BaseModel):
    model_config = ConfigDict(extra="allow")

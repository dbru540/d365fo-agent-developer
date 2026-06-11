from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class Artifact:
    name: str
    artifact_type: str
    model: str
    package: str
    classification: str
    relative_path: str
    label: str | None = None
    is_public: bool = False
    data_management_enabled: bool = False
    public_entity_name: str | None = None
    public_collection_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Relation:
    relation_type: str
    source: str
    target: str
    model: str
    relative_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class Catalog:
    models: list[str] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "models": self.models,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "relations": [relation.to_dict() for relation in self.relations],
        }


# core/contracts/__init__.py
"""
Versioned generation contracts for HERMES Phase 11.
"""

from core.contracts.blueprint import (
    ImplementationBlueprint,
    FilePlan,
    ComponentSpec,
    RouteSpec,
    DataModelSpec,
)
from core.contracts.manifest import (
    InterfaceManifest,
    ElementContract,
    CssContract,
    JsHookContract,
    JsModuleContract,
    NavLinkContract,
    AssetContract,
    StateContract,
    FormContract,
    ApiEndpointContract,
)
from core.contracts.rubric import (
    QualityRubric,
    RubricRequirement,
    QualityDimension,
)
from core.contracts.validator import (
    ContractValidator,
    ContractValidationResult,
)
from core.contracts.builder import ContractBuilder

__all__ = [
    "ContractBuilder",
    "ImplementationBlueprint",
    "FilePlan",
    "ComponentSpec",
    "RouteSpec",
    "DataModelSpec",
    "InterfaceManifest",
    "ElementContract",
    "CssContract",
    "JsHookContract",
    "JsModuleContract",
    "NavLinkContract",
    "AssetContract",
    "StateContract",
    "FormContract",
    "ApiEndpointContract",
    "QualityRubric",
    "RubricRequirement",
    "QualityDimension",
    "ContractValidator",
    "ContractValidationResult",
]

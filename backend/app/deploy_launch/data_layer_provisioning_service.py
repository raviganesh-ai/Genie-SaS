"""Real mission Cosmos DB provisioning and schema validation through Azure Resource Manager."""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Protocol


class DataLayerProvisioningError(RuntimeError):
    """Raised when mission data provisioning or schema validation fails."""


@dataclass(frozen=True)
class DataLayerProvisioningResult:
    account_name: str
    endpoint: str
    database_name: str
    container_name: str
    container_resource_id: str
    schema_version: str


class DataLayerProvisioner(Protocol):
    async def provision(
        self,
        *,
        mission_slug: str,
        resource_group_name: str,
        identity_principal_id: str,
    ) -> DataLayerProvisioningResult: ...

    async def validate_schema(
        self, *, result: DataLayerProvisioningResult
    ) -> DataLayerProvisioningResult: ...


class AzureCosmosDataLayerProvisioningService:
    """Deploys a private-auth Cosmos SQL data layer with managed-identity RBAC."""

    _API_VERSION = "2024-05-15"
    _SCHEMA_VERSION = "1.0.0"
    _DATABASE_NAME = "mission"
    _CONTAINER_NAME = "records"
    _DATA_CONTRIBUTOR_ROLE_ID = "00000000-0000-0000-0000-000000000002"

    def __init__(self, *, subscription_id: str, location: str) -> None:
        self._subscription_id = subscription_id
        self._location = location

    async def provision(
        self,
        *,
        mission_slug: str,
        resource_group_name: str,
        identity_principal_id: str,
    ) -> DataLayerProvisioningResult:
        return await asyncio.to_thread(
            self._provision_sync,
            mission_slug,
            resource_group_name,
            identity_principal_id,
        )

    async def validate_schema(
        self, *, result: DataLayerProvisioningResult
    ) -> DataLayerProvisioningResult:
        await asyncio.to_thread(self._validate_schema_sync, result)
        return result

    def _provision_sync(
        self,
        mission_slug: str,
        resource_group_name: str,
        identity_principal_id: str,
    ) -> DataLayerProvisioningResult:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.resource import ResourceManagementClient
        except ImportError as exc:
            raise DataLayerProvisioningError(
                "azure-identity and azure-mgmt-resource are required."
            ) from exc
        account_name = self._account_name(mission_slug)
        template = self._template()
        parameters = {
            "location": {"value": self._location},
            "accountName": {"value": account_name},
            "identityPrincipalId": {"value": identity_principal_id},
            "databaseName": {"value": self._DATABASE_NAME},
            "containerName": {"value": self._CONTAINER_NAME},
        }
        credential = DefaultAzureCredential()
        client = ResourceManagementClient(credential, self._subscription_id)
        try:
            poller = client.deployments.begin_create_or_update(
                resource_group_name,
                f"genie-data-{hashlib.sha256(mission_slug.encode()).hexdigest()[:10]}",
                {
                    "properties": {
                        "mode": "Incremental",
                        "template": template,
                        "parameters": parameters,
                    }
                },
            )
            deployment = poller.result()
        except Exception as exc:
            raise DataLayerProvisioningError(
                f"Azure mission data-layer deployment failed: {exc}"
            ) from exc
        finally:
            credential.close()
        outputs = getattr(getattr(deployment, "properties", None), "outputs", None) or {}
        endpoint = self._output_value(outputs, "endpoint")
        container_resource_id = self._output_value(outputs, "containerResourceId")
        return DataLayerProvisioningResult(
            account_name=account_name,
            endpoint=endpoint,
            database_name=self._DATABASE_NAME,
            container_name=self._CONTAINER_NAME,
            container_resource_id=container_resource_id,
            schema_version=self._SCHEMA_VERSION,
        )

    def _validate_schema_sync(self, result: DataLayerProvisioningResult) -> None:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.resource import ResourceManagementClient
        except ImportError as exc:
            raise DataLayerProvisioningError(
                "azure-identity and azure-mgmt-resource are required."
            ) from exc
        credential = DefaultAzureCredential()
        client = ResourceManagementClient(credential, self._subscription_id)
        try:
            resource = client.resources.get_by_id(
                result.container_resource_id,
                api_version=self._API_VERSION,
            )
            account_resource_id = result.container_resource_id.split(
                "/sqlDatabases/", maxsplit=1
            )[0]
            account = client.resources.get_by_id(
                account_resource_id,
                api_version=self._API_VERSION,
            )
        except Exception as exc:
            raise DataLayerProvisioningError(
                f"Mission data schema validation failed: {exc}"
            ) from exc
        finally:
            credential.close()
        properties = getattr(resource, "properties", None)
        resource_definition = (
            properties.get("resource", {}) if isinstance(properties, dict) else {}
        )
        partition_key = resource_definition.get("partitionKey", {})
        if partition_key.get("paths") != ["/partitionKey"]:
            raise DataLayerProvisioningError(
                "Mission data container partition key does not match schema version 1.0.0."
            )
        account_properties = getattr(account, "properties", None)
        backup_policy = (
            account_properties.get("backupPolicy", {})
            if isinstance(account_properties, dict)
            else {}
        )
        if backup_policy.get("type") != "Continuous":
            raise DataLayerProvisioningError(
                "Mission data account does not have continuous backup enabled."
            )

    @classmethod
    def _template(cls) -> dict[str, Any]:
        return {
            "$schema": (
                "https://schema.management.azure.com/schemas/"
                "2019-04-01/deploymentTemplate.json#"
            ),
            "contentVersion": "1.0.0.0",
            "parameters": {
                "location": {"type": "string"},
                "accountName": {"type": "string"},
                "identityPrincipalId": {"type": "string"},
                "databaseName": {"type": "string"},
                "containerName": {"type": "string"},
            },
            "resources": [
                {
                    "type": "Microsoft.DocumentDB/databaseAccounts",
                    "apiVersion": cls._API_VERSION,
                    "name": "[parameters('accountName')]",
                    "location": "[parameters('location')]",
                    "kind": "GlobalDocumentDB",
                    "properties": {
                        "databaseAccountOfferType": "Standard",
                        "locations": [
                            {
                                "locationName": "[parameters('location')]",
                                "failoverPriority": 0,
                            }
                        ],
                        "capabilities": [{"name": "EnableServerless"}],
                        "disableLocalAuth": True,
                        "minimalTlsVersion": "Tls12",
                        "backupPolicy": {
                            "type": "Continuous",
                            "continuousModeProperties": {
                                "tier": "Continuous7Days",
                            },
                        },
                    },
                },
                {
                    "type": "Microsoft.DocumentDB/databaseAccounts/sqlDatabases",
                    "apiVersion": cls._API_VERSION,
                    "name": "[format('{0}/{1}', parameters('accountName'), parameters('databaseName'))]",
                    "dependsOn": ["[resourceId('Microsoft.DocumentDB/databaseAccounts', parameters('accountName'))]"],
                    "properties": {"resource": {"id": "[parameters('databaseName')]"}},
                },
                {
                    "type": "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers",
                    "apiVersion": cls._API_VERSION,
                    "name": (
                        "[format('{0}/{1}/{2}', parameters('accountName'), "
                        "parameters('databaseName'), parameters('containerName'))]"
                    ),
                    "dependsOn": [
                        (
                            "[resourceId('Microsoft.DocumentDB/databaseAccounts/sqlDatabases', "
                            "parameters('accountName'), parameters('databaseName'))]"
                        )
                    ],
                    "properties": {
                        "resource": {
                            "id": "[parameters('containerName')]",
                            "partitionKey": {"paths": ["/partitionKey"], "kind": "Hash"},
                        }
                    },
                },
                {
                    "type": "Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments",
                    "apiVersion": cls._API_VERSION,
                    "name": (
                        "[format('{0}/{1}', parameters('accountName'), "
                        "guid(parameters('accountName'), parameters('identityPrincipalId')))]"
                    ),
                    "dependsOn": ["[resourceId('Microsoft.DocumentDB/databaseAccounts', parameters('accountName'))]"],
                    "properties": {
                        "roleDefinitionId": (
                            "[format('{0}/sqlRoleDefinitions/"
                            f"{cls._DATA_CONTRIBUTOR_ROLE_ID}', "
                            "resourceId('Microsoft.DocumentDB/databaseAccounts', "
                            "parameters('accountName')))]"
                        ),
                        "principalId": "[parameters('identityPrincipalId')]",
                        "scope": "[resourceId('Microsoft.DocumentDB/databaseAccounts', parameters('accountName'))]",
                    },
                },
            ],
            "outputs": {
                "endpoint": {
                    "type": "string",
                    "value": "[reference(resourceId('Microsoft.DocumentDB/databaseAccounts', parameters('accountName')), '2024-05-15').documentEndpoint]",
                },
                "containerResourceId": {
                    "type": "string",
                    "value": (
                        "[resourceId('Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers', "
                        "parameters('accountName'), parameters('databaseName'), "
                        "parameters('containerName'))]"
                    ),
                },
            },
        }

    @staticmethod
    def _account_name(mission_slug: str) -> str:
        normalized = re.sub(r"[^a-z0-9]", "", mission_slug.lower())
        suffix = hashlib.sha256(mission_slug.encode()).hexdigest()[:8]
        return f"g{normalized[:34]}{suffix}"[:44]

    @staticmethod
    def _output_value(outputs: dict[str, Any], name: str) -> str:
        output = outputs.get(name)
        value = output.get("value") if isinstance(output, dict) else None
        if not isinstance(value, str) or not value:
            raise DataLayerProvisioningError(
                f"Azure data-layer deployment omitted required output '{name}'."
            )
        return value


class UnavailableDataLayerProvisioningService:
    """Fails closed when Azure deployment configuration is incomplete."""

    async def provision(
        self,
        *,
        mission_slug: str,
        resource_group_name: str,
        identity_principal_id: str,
    ) -> DataLayerProvisioningResult:
        del mission_slug, resource_group_name, identity_principal_id
        raise DataLayerProvisioningError(
            "Mission data-layer provisioning requires Azure subscription and location settings."
        )

    async def validate_schema(
        self, *, result: DataLayerProvisioningResult
    ) -> DataLayerProvisioningResult:
        del result
        raise DataLayerProvisioningError("Mission data-layer provisioning is unavailable.")


class NullDataLayerProvisioningService:
    """Test double only: real behavior end-to-end minus any actual Azure
    calls, matching NullBackendDeploymentService/NullFrontendDeploymentService
    elsewhere in this package. Never wired into
    create_data_layer_provisioning_service - that factory remains real-or-
    fail-closed (see UnavailableDataLayerProvisioningService) since
    provisioning the mission data layer is never conditionally skippable in
    production."""

    async def provision(
        self,
        *,
        mission_slug: str,
        resource_group_name: str,
        identity_principal_id: str,
    ) -> DataLayerProvisioningResult:
        del resource_group_name, identity_principal_id
        account_name = self._account_name(mission_slug)
        return DataLayerProvisioningResult(
            account_name=account_name,
            endpoint=f"https://{account_name}.documents.azure.com:443/",
            database_name="mission-data",
            container_name="mission-items",
            container_resource_id=(
                f"local/{mission_slug}/mission-data/mission-items"
            ),
            schema_version="1.0.0",
        )

    async def validate_schema(
        self, *, result: DataLayerProvisioningResult
    ) -> DataLayerProvisioningResult:
        return result

    @staticmethod
    def _account_name(mission_slug: str) -> str:
        return f"local-{mission_slug}"


def create_data_layer_provisioning_service(
    *, subscription_id: str | None, location: str | None
) -> DataLayerProvisioner:
    if subscription_id and location:
        return AzureCosmosDataLayerProvisioningService(
            subscription_id=subscription_id,
            location=location,
        )
    return UnavailableDataLayerProvisioningService()

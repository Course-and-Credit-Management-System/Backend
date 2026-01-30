"""Tests for health check endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test health check endpoint returns healthy status."""
    response = await client.get("/api/v1/health/health")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "app_name" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_readiness_check(client: AsyncClient):
    """Test readiness check endpoint."""
    response = await client.get("/api/v1/health/ready")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "ready"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Test root endpoint."""
    response = await client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "message" in data
    assert "version" in data
    assert "docs" in data

import asyncio
import pytest
from src.core.circuit_breaker import CircuitBreaker

@pytest.mark.asyncio
async def test_circuit_breaker():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
    # Test that a successful call works.
    result = await cb.call(lambda: asyncio.sleep(0))
    assert result is None

    # Function that always fails.
    async def failing_call():
        raise Exception("failure")
    
    # Intentionally trigger failures to test the circuit breaker's failure threshold.
    with pytest.raises(Exception):
        await cb.call(failing_call)
    with pytest.raises(Exception):
        await cb.call(failing_call)
    with pytest.raises(Exception):
        await cb.call(failing_call)
    
    # The circuit breaker should now be in an open state due to the failure threshold being reached.
    with pytest.raises(Exception):
        await cb.call(failing_call)
    
    # Wait for the recovery timeout to allow the circuit breaker to transition to a half-open state.
    await asyncio.sleep(1.1)
    try:
        await cb.call(lambda: asyncio.sleep(0) or "success")
    except Exception:
        pytest.fail("Circuit breaker did not allow a call in half-open state")

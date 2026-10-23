"""Compatibility alias for TestOmegaExecutionRouter test suite.

Allows test discovery under both test_omega_execution_router and test_omega_execution_router_and_lifecycle.
"""

try:
    from agents.AGI_1_7.tests.test_omega_execution_router import (  # noqa: F401
        TestOmegaExecutionRouter,
    )
except ImportError:
    from test_omega_execution_router import (  # noqa: F401
        TestOmegaExecutionRouter,
    )

if __name__ == "__main__":
    import unittest
    unittest.main()

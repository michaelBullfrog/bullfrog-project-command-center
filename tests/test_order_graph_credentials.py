import os
import unittest
from unittest.mock import AsyncMock, patch

import main


class FakeTokenResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"access_token": "orders-token"}


class OrderGraphCredentialTests(unittest.IsolatedAsyncioTestCase):
    def test_dedicated_credentials_take_precedence(self):
        environment = {
            "MS_TENANT_ID": "shared-tenant",
            "MS_CLIENT_ID": "shared-client",
            "MS_CLIENT_SECRET": "shared-secret",
            "ORDER_GRAPH_TENANT_ID": "orders-tenant",
            "ORDER_GRAPH_CLIENT_ID": "orders-client",
            "ORDER_GRAPH_CLIENT_SECRET": "orders-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                main.order_graph_credentials(),
                ("orders-tenant", "orders-client", "orders-secret"),
            )
            self.assertTrue(main.order_graph_configured())

    def test_shared_credentials_are_a_backward_compatible_fallback(self):
        environment = {
            "MS_TENANT_ID": "shared-tenant",
            "MS_CLIENT_ID": "shared-client",
            "MS_CLIENT_SECRET": "shared-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                main.order_graph_credentials(),
                ("shared-tenant", "shared-client", "shared-secret"),
            )
            self.assertTrue(main.order_graph_configured())

    async def test_token_request_uses_dedicated_credentials(self):
        client = AsyncMock()
        client.post.return_value = FakeTokenResponse()
        environment = {
            "ORDER_GRAPH_TENANT_ID": "orders-tenant",
            "ORDER_GRAPH_CLIENT_ID": "orders-client",
            "ORDER_GRAPH_CLIENT_SECRET": "orders-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            token = await main.order_graph_access_token(client)

        self.assertEqual(token, "orders-token")
        client.post.assert_awaited_once()
        _, kwargs = client.post.await_args
        self.assertEqual(kwargs["data"]["client_id"], "orders-client")
        self.assertEqual(kwargs["data"]["client_secret"], "orders-secret")


if __name__ == "__main__":
    unittest.main()
